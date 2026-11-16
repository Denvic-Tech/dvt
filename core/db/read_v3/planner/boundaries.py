from __future__ import annotations

import logging
import math
from decimal import Decimal
from typing import Any, Optional, Sequence

import pandas as pd
from sqlalchemy.engine import Engine

from core.db.read_v3.dialects.base import SQLDialect, to_python_scalar
from core.db.read_v3.errors import ReadV3PlanningError
from core.db.read_v3.models import PartitionStrategy, ReadSegment, SegmentDivision
from core.db.read_v3.sql_runner import read_sql_df

logger = logging.getLogger(__name__)

RANGE_BOUNDARIES_SINGLE_QUERY = "single_query"
RANGE_BOUNDARIES_OFFSET_LOOP = "offset_loop"
_INT64_MIN = -(2**63)
_UINT64_MAX = 2**64 - 1


def _with_cte(cte_prefix_sql: Optional[str], sql: str) -> str:
    if cte_prefix_sql:
        return f"{cte_prefix_sql} {sql}"
    return sql


def query_df(engine: Engine, sql: str) -> pd.DataFrame:
    return read_sql_df(engine, sql)


def query_scalar(engine: Engine, sql: str, column: str) -> Any:
    df = query_df(engine, sql)
    if df.empty:
        raise ReadV3PlanningError(f"Expected at least one row for scalar SQL: {sql}")
    if column not in df.columns:
        raise ReadV3PlanningError(
            f"Scalar query did not return required column {column!r}. columns={list(df.columns)!r}"
        )
    return df.iloc[0][column]


def query_row_stats(
    *,
    engine: Engine,
    dialect: SQLDialect,
    cte_prefix_sql: Optional[str],
    relation_sql: str,
    key_sql: str,
) -> tuple[Any, Any, int, int]:
    sql = _with_cte(cte_prefix_sql, dialect.min_max_query(relation_sql, key_sql))
    df = query_df(engine, sql)

    def _first(column: str) -> Any:
        # Read column by column: a row of an Int64 key next to UInt64 counts (clickhouse_connect)
        # upcasts to float64, which rounds keys above 2**53.
        return df[column].iloc[0] if column in df.columns else None

    min_v = _first("min_v")
    max_v = _first("max_v")
    total_rows = int(_first("total_rows") or 0)
    non_null_rows = int(_first("non_null_rows") or 0)
    return min_v, max_v, total_rows, non_null_rows


def _single_query_boundaries(
    *,
    engine: Engine,
    dialect: SQLDialect,
    cte_prefix_sql: str | None,
    relation_sql: str,
    key_sql: str,
    page_size: int,
    non_null_rows: int,
) -> list[Any]:
    sql = _with_cte(
        cte_prefix_sql,
        dialect.range_boundaries_query(
            relation_sql,
            key_sql,
            page_size=page_size,
            non_null_rows=non_null_rows,
        ),
    )
    df = query_df(engine, sql)
    if df.empty or "boundary_value" not in df.columns:
        raise ReadV3PlanningError(
            f"Range boundaries query returned no boundary_value rows. columns={list(df.columns)!r}"
        )
    column = df["boundary_value"]
    # Positional access returns the same scalar types as query_scalar on a one-row result.
    return [column.iloc[idx] for idx in range(len(column))]


def _offset_loop_boundaries(
    *,
    engine: Engine,
    dialect: SQLDialect,
    cte_prefix_sql: str | None,
    relation_sql: str,
    key_sql: str,
    page_size: int,
    non_null_rows: int,
) -> list[Any]:
    boundaries: list[Any] = []
    for offset in range(0, non_null_rows, page_size):
        sql = _with_cte(cte_prefix_sql, dialect.boundary_query(relation_sql, key_sql, offset))
        boundaries.append(query_scalar(engine, sql, "boundary_value"))
    return boundaries


def query_range_boundaries(
    *,
    engine: Engine,
    dialect: SQLDialect,
    cte_prefix_sql: str | None,
    relation_sql: str,
    key_sql: str,
    page_size: int,
    non_null_rows: int,
) -> tuple[list[Any], str]:
    """Key values at 0-based ranks ``0, page_size, ...`` of the ascending non-NULL key order.

    One statement (``SQLDialect.range_boundaries_query``) when the dialect has it, otherwise or
    when that statement fails one ``boundary_query`` per boundary. Returns the values and a
    short status for the plan warnings.
    """
    try:
        boundaries = _single_query_boundaries(
            engine=engine,
            dialect=dialect,
            cte_prefix_sql=cte_prefix_sql,
            relation_sql=relation_sql,
            key_sql=key_sql,
            page_size=page_size,
            non_null_rows=non_null_rows,
        )
    except NotImplementedError:
        status = RANGE_BOUNDARIES_OFFSET_LOOP
    except Exception as exc:  # the per-boundary queries return the same values
        logger.warning(
            "read_v3 single-query range boundaries failed for key %s, "
            "falling back to one query per boundary: %s",
            key_sql,
            exc,
        )
        status = f"{RANGE_BOUNDARIES_OFFSET_LOOP}(single query failed: {type(exc).__name__})"
    else:
        return boundaries, RANGE_BOUNDARIES_SINGLE_QUERY
    boundaries = _offset_loop_boundaries(
        engine=engine,
        dialect=dialect,
        cte_prefix_sql=cte_prefix_sql,
        relation_sql=relation_sql,
        key_sql=key_sql,
        page_size=page_size,
        non_null_rows=non_null_rows,
    )
    return boundaries, status


def _integral_as_int(value: Any) -> Any:
    """An integral number of an integer key as a Python int: ``5``, not ``'5'`` or ``5.0``.

    Only within the 64-bit range: ClickHouse parses a longer integer literal as Float64, while
    a quoted Decimal stays exact.
    """
    value = to_python_scalar(value)
    if not isinstance(value, (float, Decimal)) or not math.isfinite(value) or value != int(value):
        return value
    integral = int(value)
    return integral if _INT64_MIN <= integral <= _UINT64_MAX else value


def build_range_segments(
    *,
    engine: Engine,
    dialect: SQLDialect,
    cte_prefix_sql: Optional[str],
    relation_sql: str,
    key_sql: str,
    npartitions: int,
    integer_key: bool = False,
) -> tuple[list[ReadSegment], tuple[Any, ...], int, int, str]:
    """Range segments, divisions, row counts and how the boundaries were read.

    ``integer_key`` (an integer DB type) renders and divides integral bounds as Python ints,
    whatever the driver returned: ``Decimal`` for ``numeric(18, 0)``, numpy scalars.
    """
    min_v, max_v, total_rows, non_null_rows = query_row_stats(
        engine=engine,
        dialect=dialect,
        cte_prefix_sql=cte_prefix_sql,
        relation_sql=relation_sql,
        key_sql=key_sql,
    )
    if total_rows == 0:
        empty_segment = ReadSegment(
            label="empty",
            predicate_sql="1=0",
            order_by_sql=f"ORDER BY {key_sql} ASC",
            division=SegmentDivision(start=0, end=1, include_end=True),
            strategy=PartitionStrategy.RANGE,
            expected_rows=0,
        )
        return [empty_segment], (0, 1), total_rows, non_null_rows, "skipped(empty relation)"

    if non_null_rows == 0:
        raise ReadV3PlanningError(
            "Range segmentation cannot be built because partition key contains only NULL values"
        )

    effective_parts = max(1, npartitions)
    if total_rows > 0:
        effective_parts = min(effective_parts, total_rows)
    page_size = max(1, math.ceil(non_null_rows / effective_parts))

    raw_boundaries, boundaries_method = query_range_boundaries(
        engine=engine,
        dialect=dialect,
        cte_prefix_sql=cte_prefix_sql,
        relation_sql=relation_sql,
        key_sql=key_sql,
        page_size=page_size,
        non_null_rows=non_null_rows,
    )

    if min_v is not None:
        raw_boundaries.insert(0, min_v)
    if max_v is not None:
        raw_boundaries.append(max_v)
    if integer_key:
        raw_boundaries = [_integral_as_int(value) for value in raw_boundaries]

    boundaries: list[Any] = []
    for value in raw_boundaries:
        if value is None:
            continue
        if not boundaries or boundaries[-1] != value:
            boundaries.append(value)

    if len(boundaries) == 1:
        boundaries.append(boundaries[0])

    if len(boundaries) < 2:
        raise ReadV3PlanningError(
            f"Failed to build at least two range boundaries for key={key_sql!r}"
        )

    segments: list[ReadSegment] = []
    for idx in range(len(boundaries) - 1):
        start = boundaries[idx]
        end = boundaries[idx + 1]
        is_last = idx == len(boundaries) - 2
        if start == end and not is_last:
            continue
        if start == end and is_last:
            predicate = f"{key_sql} = {dialect.render_literal(start)}"
        else:
            op = "<=" if is_last else "<"
            predicate = (
                f"{key_sql} >= {dialect.render_literal(start)} "
                f"AND {key_sql} {op} {dialect.render_literal(end)}"
            )
        segments.append(
            ReadSegment(
                label=f"range_{idx}",
                predicate_sql=predicate,
                order_by_sql=f"ORDER BY {key_sql} ASC",
                division=SegmentDivision(start=start, end=end, include_end=is_last),
                strategy=PartitionStrategy.RANGE,
            )
        )

    if not segments:
        raise ReadV3PlanningError("No non-empty range segments were generated")

    divisions = [segments[0].division.start]
    for segment in segments:
        divisions.append(segment.division.end)

    return segments, tuple(divisions), total_rows, non_null_rows, boundaries_method


def build_hash_segments(
    *,
    key_sql: str,
    hash_sql: str,
    npartitions: int,
    total_rows: int = 0,
) -> tuple[list[ReadSegment], tuple[int, ...], int]:
    buckets = max(1, npartitions)
    if 0 < total_rows < buckets:
        buckets = total_rows
    segments: list[ReadSegment] = []
    divisions = [0]

    for bucket in range(buckets):
        start_bucket = bucket
        end_bucket = bucket + 1
        predicate = f"{hash_sql} = {bucket}"
        segments.append(
            ReadSegment(
                label=f"bucket_{bucket}",
                predicate_sql=predicate,
                order_by_sql=f"ORDER BY {hash_sql} ASC, {key_sql} ASC",
                division=SegmentDivision(start=start_bucket, end=end_bucket, include_end=True),
                strategy=PartitionStrategy.HASH,
                bucket_start=start_bucket,
                bucket_end=end_bucket,
            )
        )
        divisions.append(end_bucket)

    return segments, tuple(divisions), buckets


def infer_npartitions(total_rows: int, explicit_npartitions: Optional[int]) -> int:
    if explicit_npartitions is not None:
        if explicit_npartitions <= 0:
            raise ReadV3PlanningError("npartitions must be positive")
        if total_rows <= 0:
            return 1
        return min(explicit_npartitions, total_rows)
    if total_rows <= 0:
        return 1
    return max(1, min(64, math.ceil(total_rows / 100_000)))


def clamp_npartitions(npartitions: int, total_rows: int) -> int:
    """Target partition count limited to the row count (one partition for an empty relation)."""
    return 1 if total_rows <= 0 else min(npartitions, total_rows)


def default_max_rows_per_partition(total_rows: int, npartitions: int) -> int:
    """Planner row ceiling per segment when the user sets none: 4x the mean, at least 100 000."""
    baseline = max(1, math.ceil(max(total_rows, 1) / max(npartitions, 1)))
    return max(100_000, baseline * 4)
