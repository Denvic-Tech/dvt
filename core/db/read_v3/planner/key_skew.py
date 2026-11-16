"""Planning-time check that no single partition-key value exceeds the segment row ceiling.

Range boundaries and hash buckets never divide rows that share one key value (NULL keys share one
hash bucket), so such a value alone above ``max_rows_per_partition`` makes a read fail on that
segment. The check looks the heaviest value up before any segment query runs:

- dialects with ``SQLDialect.heaviest_value_query`` (ClickHouse): one exact ``GROUP BY``;
- dialects with ``SQLDialect.column_statistics_query`` (PostgreSQL tables): the ANALYZE estimate
  of the most common value and of the NULL fraction;
- other dialects: skipped; the executor ceiling stays the last line.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import pandas as pd
from sqlalchemy.engine import Engine

from core.db.read_v3.dialects.base import SQLDialect
from core.db.read_v3.errors import ReadV3PlanningError
from core.db.read_v3.sql_runner import read_sql_df

QueryDf = Callable[[str], pd.DataFrame]

# An estimated count must exceed the ceiling by this factor before planning fails, so that the
# sampling error of ANALYZE statistics does not block a read that would fit.
ESTIMATE_MARGIN = 1.25

ADVICE_HINT = (
    "Choose another partition_col or raise max_rows_per_partition above that count. "
    "The suggest_read_partitioning MCP tool and the Gateway endpoint "
    "POST /db-connections/{connection_id}/partitioning-advice profile candidate keys."
)


@dataclass(frozen=True)
class CatalogColumnStats:
    """Database catalog statistics of one column (PostgreSQL ``pg_stats``)."""

    column: str
    null_frac: float | None
    n_distinct: float | None
    top_value: str | None
    top_freq: float | None
    hist_min: str | None
    hist_max: str | None


@dataclass(frozen=True)
class HeaviestKeyValue:
    value: Any
    count: int
    estimated: bool
    source: str


def with_cte(cte_prefix_sql: str | None, sql: str) -> str:
    if cte_prefix_sql:
        return f"{cte_prefix_sql} {sql}"
    return sql


def plain_value(value: Any) -> Any:
    """Convert pandas/numpy scalars to plain Python values; NaN/NaT/NA become None."""
    try:
        missing = value is None or bool(pd.isna(value))
    except (TypeError, ValueError):  # array-like values
        missing = False
    if missing:
        result = None
    elif isinstance(value, pd.Timestamp):
        result = value.to_pydatetime()
    elif hasattr(value, "item") and not isinstance(value, (str, bytes)):
        try:
            result = value.item()
        except (AttributeError, ValueError):
            result = value
    else:
        result = value
    return result


def show_key_value(value: Any) -> str:
    """Key value for messages: strings quoted, dates and numbers as plain text."""
    return repr(value) if isinstance(value, str) else str(value)


def first_row(df: pd.DataFrame) -> dict[str, Any]:
    """First row with per-column types (``df.iloc[0]`` upcasts mixed int/float columns)."""
    return df.iloc[:1].to_dict("records")[0]


def _float_or_none(value: Any) -> float | None:
    value = plain_value(value)
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(result) else result


def _str_or_none(value: Any) -> str | None:
    value = plain_value(value)
    return None if value is None else str(value)


def read_catalog_column_stats(
    *,
    dialect: SQLDialect,
    table_name: str,
    schema: str | None,
    column_names: Sequence[str],
    query_df: QueryDf,
) -> dict[str, CatalogColumnStats] | None:
    """Catalog statistics by column name, or None when the dialect has no catalog statistics."""
    try:
        sql = dialect.column_statistics_query(
            table_name=table_name,
            schema=schema,
            column_names=column_names,
        )
    except NotImplementedError:
        return None
    df = query_df(sql)
    result: dict[str, CatalogColumnStats] = {}
    if df.empty:
        return result
    # Inherited rows describe the parent with its children, which is what a read of it returns.
    rows = sorted(
        df.to_dict("records"),
        key=lambda row: not bool(plain_value(row.get("inherited"))),
    )
    for row in rows:
        name = str(row.get("column_name"))
        result.setdefault(
            name,
            CatalogColumnStats(
                column=name,
                null_frac=_float_or_none(row.get("null_frac")),
                n_distinct=_float_or_none(row.get("n_distinct")),
                top_value=_str_or_none(row.get("top_value")),
                top_freq=_float_or_none(row.get("top_freq")),
                hist_min=_str_or_none(row.get("hist_min")),
                hist_max=_str_or_none(row.get("hist_max")),
            ),
        )
    return result


def find_heaviest_key_value(
    *,
    engine: Engine,
    dialect: SQLDialect,
    cte_prefix_sql: str | None,
    relation_sql: str,
    key_sql: str,
    key_name: str,
    total_rows: int,
    table_name: str | None = None,
    schema: str | None = None,
    query_df: QueryDf | None = None,
) -> HeaviestKeyValue | None:
    """Most repeated key value (NULL included) or None when no cheap lookup exists.

    ``table_name`` enables the catalog estimate; pass it only when the relation is that whole
    table (no ``limit``), because catalog frequencies describe the table.
    """
    run = query_df or (lambda sql: read_sql_df(engine, sql))
    try:
        sql = dialect.heaviest_value_query(relation_sql, key_sql)
    except NotImplementedError:
        sql = None
    if sql is not None:
        df = run(with_cte(cte_prefix_sql, sql))
        if df.empty:
            return None
        row = first_row(df)
        return HeaviestKeyValue(
            value=plain_value(row["dvt_heavy_value"]),
            count=int(row["dvt_heavy_count"]),
            estimated=False,
            source="exact",
        )

    if table_name is None or total_rows <= 0:
        return None
    stats = read_catalog_column_stats(
        dialect=dialect,
        table_name=table_name,
        schema=schema,
        column_names=[key_name],
        query_df=run,
    )
    column = (stats or {}).get(key_name)
    if column is None:
        return None
    candidates: list[HeaviestKeyValue] = []
    if column.top_freq:
        candidates.append(
            HeaviestKeyValue(
                value=column.top_value,
                count=round(column.top_freq * total_rows),
                estimated=True,
                source="pg_stats",
            )
        )
    if column.null_frac:
        candidates.append(
            HeaviestKeyValue(
                value=None,
                count=round(column.null_frac * total_rows),
                estimated=True,
                source="pg_stats",
            )
        )
    if not candidates:
        return None
    return max(candidates, key=lambda candidate: candidate.count)


def check_partition_key_skew(
    *,
    engine: Engine,
    dialect: SQLDialect,
    cte_prefix_sql: str | None,
    relation_sql: str,
    key_sql: str,
    key_name: str,
    total_rows: int,
    max_rows_per_partition: int,
    table_name: str | None = None,
    schema: str | None = None,
) -> str:
    """Raise ``ReadV3PlanningError`` when one key value exceeds the ceiling.

    Returns a short status for the plan warnings. Lookup failures skip the check: it is an
    early diagnosis, the executor ceiling still guards every segment.
    """
    if total_rows <= max_rows_per_partition:
        return "skipped(relation fits one segment)"
    try:
        heavy = find_heaviest_key_value(
            engine=engine,
            dialect=dialect,
            cte_prefix_sql=cte_prefix_sql,
            relation_sql=relation_sql,
            key_sql=key_sql,
            key_name=key_name,
            total_rows=total_rows,
            table_name=table_name,
            schema=schema,
        )
    except Exception as exc:  # advisory lookup, see the docstring
        return f"skipped({type(exc).__name__})"
    if heavy is None:
        return f"skipped(no cheap lookup for dialect {dialect.name})"

    limit = max_rows_per_partition * (ESTIMATE_MARGIN if heavy.estimated else 1)
    if heavy.count <= limit:
        return f"ok(max_repeat={heavy.count}, source={heavy.source})"

    subject = (
        "NULL keys occur" if heavy.value is None else f"value {show_key_value(heavy.value)} occurs"
    )
    estimate = f" (estimate from {heavy.source})" if heavy.estimated else ""
    raise ReadV3PlanningError(
        f"Partition key {key_name!r} cannot be split into segments of at most "
        f"max_rows_per_partition={max_rows_per_partition} rows: {subject} {heavy.count} "
        f"times{estimate}. Range and hash segments never divide rows with the same key value, "
        f"and NULL keys share one hash bucket. {ADVICE_HINT}"
    )
