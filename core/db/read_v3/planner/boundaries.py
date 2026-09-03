from __future__ import annotations

import math
from typing import Any, Optional, Sequence

import pandas as pd
from sqlalchemy.engine import Engine

from core.db.read_v3.dialects.base import SQLDialect
from core.db.read_v3.errors import ReadV3PlanningError
from core.db.read_v3.models import PartitionStrategy, ReadSegment, SegmentDivision
from core.db.read_v3.sql_runner import read_sql_df


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
    row = query_df(engine, sql).iloc[0]
    min_v = row.get("min_v")
    max_v = row.get("max_v")
    total_rows = int(row.get("total_rows") or 0)
    non_null_rows = int(row.get("non_null_rows") or 0)
    return min_v, max_v, total_rows, non_null_rows


def build_range_segments(
    *,
    engine: Engine,
    dialect: SQLDialect,
    cte_prefix_sql: Optional[str],
    relation_sql: str,
    key_sql: str,
    npartitions: int,
) -> tuple[list[ReadSegment], tuple[Any, ...], int, int]:
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
        return [empty_segment], (0, 1), total_rows, non_null_rows

    if non_null_rows == 0:
        raise ReadV3PlanningError(
            "Range segmentation cannot be built because partition key contains only NULL values"
        )

    effective_parts = max(1, npartitions)
    if total_rows > 0:
        effective_parts = min(effective_parts, total_rows)
    page_size = max(1, math.ceil(non_null_rows / effective_parts))
    offsets = list(range(0, non_null_rows, page_size))

    raw_boundaries: list[Any] = []
    for offset in offsets:
        sql = _with_cte(cte_prefix_sql, dialect.boundary_query(relation_sql, key_sql, offset))
        boundary_value = query_scalar(engine, sql, "boundary_value")
        raw_boundaries.append(boundary_value)

    if min_v is not None:
        raw_boundaries.insert(0, min_v)
    if max_v is not None:
        raw_boundaries.append(max_v)

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

    return segments, tuple(divisions), total_rows, non_null_rows


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
