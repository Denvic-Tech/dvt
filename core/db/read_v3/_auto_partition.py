from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import pandas as pd
import sqlalchemy as sa
from sqlalchemy.engine import Engine

from core.db.read_v3.dialects.base import SQLDialect
from core.db.read_v3.sql_runner import read_sql_df

SMART_BPR_SAMPLE_ROWS = 1_000
TABLE_BPR_SAFETY_COEF = 1.2
QUERY_BPR_SAFETY_COEF = 1.0
DEFAULT_VARCHAR_BYTES = 64
ROW_OVERHEAD_BYTES = 24
READ_TO_WRITE_PART_MULTIPLIER = 2

DIALECT_WRITE_BATCH_ROWS = {
    "clickhouse": 1_000_000,
    "postgresql": 40_000,
    "mysql": 50_000,
    "mariadb": 50_000,
    "sqlite": 5_000,
    "mssql": 60_000,
    "oracle": 40_000,
    "duckdb": 100_000,
}


@dataclass(frozen=True)
class AutoPartitionEstimate:
    npartitions: int
    rows_per_part: int
    bytes_per_row_est: int
    effective_rows_est: int
    effective_bytes_est: int
    dialect: str


def _with_safety(raw_bpr: float, *, safety_coef: float) -> int:
    return max(1, math.ceil(raw_bpr * safety_coef + ROW_OVERHEAD_BYTES))


def _safe_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _heuristic_col_width(type_obj: object, type_repr: str = "") -> int:  # noqa: PLR0911
    raw = (type_repr or str(type_obj or "")).lower()
    if any(token in raw for token in ("int", "serial", "bigint", "smallint")):
        return 8
    if "bool" in raw or raw.strip() == "bit":
        return 1
    if any(token in raw for token in ("float", "double", "real")):
        return 8
    if any(token in raw for token in ("decimal", "numeric", "number", "money")):
        return 16
    if "date" in raw and "time" not in raw:
        return 4
    if "time" in raw:
        return 8
    if "uuid" in raw:
        return 16
    if "json" in raw or "xml" in raw:
        return 128
    if any(
        token in raw for token in ("text", "varchar", "char", "string", "clob", "nchar", "nvarchar")
    ):
        length = _safe_int(getattr(type_obj, "length", None))
        if length:
            return min(max(8, int(length // 4)), 256)
        return DEFAULT_VARCHAR_BYTES
    return 16


def _estimate_from_dataframe(df: pd.DataFrame, *, safety_coef: float) -> int | None:
    if df.empty:
        return None
    raw_bpr = df.memory_usage(deep=True).sum() / max(1, len(df))
    return _with_safety(raw_bpr, safety_coef=safety_coef)


def _finalize_estimate(
    *,
    dialect_name: str,
    bytes_per_row_est: int,
    effective_rows_est: int,
    min_rows_per_part: int,
    target_partition_mem_mb: int,
    partitioning_overhead_coef: float,
    max_partitions: int,
) -> AutoPartitionEstimate:
    write_batch_rows = DIALECT_WRITE_BATCH_ROWS.get(dialect_name, 50_000)
    target_bytes = max(
        1,
        int(target_partition_mem_mb * 1024**2 * partitioning_overhead_coef),
    )
    effective_bytes_est = max(0, effective_rows_est) * max(1, bytes_per_row_est)
    nparts_by_bytes = max(1, math.ceil(max(1, effective_bytes_est) / target_bytes))
    base_rows_per_part = max(
        min_rows_per_part,
        READ_TO_WRITE_PART_MULTIPLIER * write_batch_rows,
    )
    rows_per_part_by_mem = max(1, int(target_bytes / max(1, bytes_per_row_est)))
    target_rows_per_part = max(
        min_rows_per_part,
        min(base_rows_per_part, rows_per_part_by_mem),
    )
    if effective_rows_est > 0:
        nparts_by_rows = max(1, math.ceil(effective_rows_est / target_rows_per_part))
        npartitions = max(nparts_by_bytes, nparts_by_rows)
        npartitions = min(npartitions, effective_rows_est)
    else:
        npartitions = 1
    npartitions = max(1, min(npartitions, max_partitions))
    if effective_rows_est > 0:
        rows_per_part = max(1, math.ceil(effective_rows_est / npartitions))
    else:
        rows_per_part = 0
    return AutoPartitionEstimate(
        npartitions=int(npartitions),
        rows_per_part=int(rows_per_part),
        bytes_per_row_est=int(bytes_per_row_est),
        effective_rows_est=int(effective_rows_est),
        effective_bytes_est=int(effective_bytes_est),
        dialect=dialect_name,
    )


def _table_bytes_and_rows(
    engine: Engine,
    dialect: SQLDialect,
    table_name: str,
    schema: str | None,
) -> tuple[int, int | None]:
    dialect_name = dialect.name.lower()
    full_name = dialect.full_table_name(table_name, schema)
    if dialect_name == "clickhouse":
        with engine.connect() as conn:
            total_bytes = int(
                conn.execute(
                    sa.text(
                        """
                        SELECT sum(data_uncompressed_bytes)
                        FROM system.parts
                        WHERE database = :db AND table = :tbl AND active = 1
                        """
                    ),
                    {"db": schema or engine.url.database, "tbl": table_name},
                ).scalar()
                or 0
            )
            total_rows = conn.execute(
                sa.text(
                    """
                    SELECT sum(rows)
                    FROM system.parts
                    WHERE database = :db AND table = :tbl AND active = 1
                    """
                ),
                {"db": schema or engine.url.database, "tbl": table_name},
            ).scalar()
        return total_bytes, _safe_int(total_rows)

    if dialect_name == "postgresql":
        with engine.connect() as conn:
            total_bytes = int(
                conn.execute(
                    sa.text("SELECT pg_total_relation_size(:fq)"), {"fq": full_name}
                ).scalar()
                or 0
            )
            total_rows = conn.execute(
                sa.text(
                    """
                    SELECT reltuples::bigint
                    FROM pg_class
                    WHERE oid = CAST(:fq AS regclass)
                    """
                ),
                {"fq": full_name},
            ).scalar()
        return total_bytes, _safe_int(total_rows)

    if dialect_name in {"mysql", "mariadb"}:
        with engine.connect() as conn:
            row = conn.execute(
                sa.text(
                    """
                    SELECT DATA_LENGTH + INDEX_LENGTH AS total_bytes, TABLE_ROWS
                    FROM information_schema.TABLES
                    WHERE TABLE_SCHEMA = :db AND TABLE_NAME = :tbl
                    """
                ),
                {"db": schema or engine.url.database, "tbl": table_name},
            ).first()
        if row is None:
            return 0, None
        return int(row.total_bytes or 0), _safe_int(row.TABLE_ROWS)

    if dialect_name in {"mssql", "sqlserver", "oracle", "sqlite"}:
        with engine.connect() as conn:
            total_rows = conn.execute(sa.text(f"SELECT COUNT(*) FROM {full_name}")).scalar()
        total_rows_int = int(total_rows or 0)
        return total_rows_int * DEFAULT_VARCHAR_BYTES, total_rows_int

    with engine.connect() as conn:
        total_rows = conn.execute(sa.text(f"SELECT COUNT(*) FROM {full_name}")).scalar()
    total_rows_int = int(total_rows or 0)
    return total_rows_int * DEFAULT_VARCHAR_BYTES, total_rows_int


def _column_avg_bytes_from_metadata(  # noqa: PLR0911
    engine: Engine,
    dialect_name: str,
    table_name: str,
    schema: str | None,
) -> dict[str, float] | None:
    if dialect_name == "clickhouse":
        with engine.connect() as conn:
            rows = conn.execute(
                sa.text(
                    """
                    SELECT column, sum(data_uncompressed_bytes) AS uncompressed_bytes, sum(rows) AS r
                    FROM system.parts_columns
                    WHERE database = :db AND table = :tbl AND active = 1
                    GROUP BY column
                    """
                ),
                {"db": schema or engine.url.database, "tbl": table_name},
            ).fetchall()
        if not rows:
            return None
        result: dict[str, float] = {}
        for row in rows:
            row_count = _safe_int(row.r) or 0
            if row_count > 0:
                result[str(row.column)] = float(row.uncompressed_bytes) / row_count
        return result or None

    if dialect_name == "postgresql":
        full_name = f"{schema}.{table_name}" if schema else table_name
        with engine.connect() as conn:
            rows = conn.execute(
                sa.text(
                    """
                    SELECT attname AS column, avg_width
                    FROM pg_stats
                    WHERE (schemaname || '.' || tablename) = :fq
                    """
                ),
                {"fq": full_name},
            ).fetchall()
        if not rows:
            return None
        return {str(row.column): float(row.avg_width) for row in rows if row.avg_width is not None}

    if dialect_name == "oracle":
        with engine.connect() as conn:
            rows = conn.execute(
                sa.text(
                    """
                    SELECT COLUMN_NAME AS column, AVG_COL_LEN
                    FROM USER_TAB_COLUMNS
                    WHERE TABLE_NAME = UPPER(:tbl)
                    """
                ),
                {"tbl": table_name},
            ).fetchall()
        if not rows:
            return None
        return {
            str(row.column): float(row.AVG_COL_LEN) for row in rows if row.AVG_COL_LEN is not None
        }

    return None


def _sample_table_rows(
    *,
    engine: Engine,
    dialect: SQLDialect,
    table_name: str,
    schema: str | None,
    selected_columns: Sequence[str],
    sample_rows: int,
) -> pd.DataFrame:
    columns_sql = ", ".join(dialect.quote_ident(column) for column in selected_columns)
    table_sql = dialect.full_table_name(table_name, schema)
    sample_sql = dialect.cap_rows_sql(f"SELECT {columns_sql} FROM {table_sql}", sample_rows)
    return read_sql_df(engine, sample_sql)


def _sample_query_rows(
    *,
    engine: Engine,
    dialect: SQLDialect,
    cte_prefix_sql: str,
    relation_sql: str,
    selected_sql_columns: Sequence[str],
    sample_rows: int,
) -> pd.DataFrame:
    columns_sql = ", ".join(dialect.quote_result_column(column) for column in selected_sql_columns)
    base_sql = f"{cte_prefix_sql} SELECT {columns_sql} {relation_sql}".strip()
    sample_sql = dialect.cap_rows_sql(base_sql, sample_rows)
    return read_sql_df(engine, sample_sql)


def estimate_table_partitions(
    *,
    engine: Engine,
    dialect: SQLDialect,
    table_name: str,
    schema: str | None,
    selected_columns: Sequence[str],
    columns_info: Sequence[dict[str, object]],
    effective_rows_est: int,
    min_rows_per_part: int,
    target_partition_mem_mb: int,
    partitioning_overhead_coef: float,
    max_partitions: int,
) -> AutoPartitionEstimate:
    column_info_by_name = {str(column["name"]): column for column in columns_info}
    all_columns = [str(column["name"]) for column in columns_info]
    dialect_name = dialect.name.lower()

    bytes_per_row_est: int | None = None
    try:
        avg_bytes = _column_avg_bytes_from_metadata(engine, dialect_name, table_name, schema)
    except Exception:
        avg_bytes = None
    if avg_bytes:
        total = 0.0
        for column in selected_columns:
            column_info = column_info_by_name[column]
            total += avg_bytes.get(column) or _heuristic_col_width(
                column_info.get("type"),
                str(column_info.get("type") or ""),
            )
        bytes_per_row_est = _with_safety(total, safety_coef=TABLE_BPR_SAFETY_COEF)

    total_bytes = 0
    total_rows = None
    try:
        total_bytes, total_rows = _table_bytes_and_rows(engine, dialect, table_name, schema)
    except Exception:
        total_bytes, total_rows = 0, None

    if bytes_per_row_est is None and avg_bytes and total_bytes and total_rows:
        table_bpr = total_bytes / total_rows
        selected_sum = 0.0
        all_sum = 0.0
        for column in all_columns:
            column_info = column_info_by_name[column]
            avg_col = avg_bytes.get(column) or _heuristic_col_width(
                column_info.get("type"),
                str(column_info.get("type") or ""),
            )
            all_sum += float(avg_col)
            if column in selected_columns:
                selected_sum += float(avg_col)
        if all_sum > 0:
            bytes_per_row_est = _with_safety(
                table_bpr * (selected_sum / all_sum),
                safety_coef=TABLE_BPR_SAFETY_COEF,
            )

    if bytes_per_row_est is None and selected_columns:
        try:
            sample_df = _sample_table_rows(
                engine=engine,
                dialect=dialect,
                table_name=table_name,
                schema=schema,
                selected_columns=selected_columns,
                sample_rows=SMART_BPR_SAMPLE_ROWS,
            )
        except Exception:
            sample_df = pd.DataFrame()
        bytes_per_row_est = _estimate_from_dataframe(
            sample_df,
            safety_coef=TABLE_BPR_SAFETY_COEF,
        )

    if bytes_per_row_est is None:
        heuristic_total = 0
        for column in selected_columns:
            column_info = column_info_by_name[column]
            heuristic_total += _heuristic_col_width(
                column_info.get("type"),
                str(column_info.get("type") or ""),
            )
        bytes_per_row_est = _with_safety(
            heuristic_total or 1024.0,
            safety_coef=TABLE_BPR_SAFETY_COEF,
        )

    return _finalize_estimate(
        dialect_name=dialect_name,
        bytes_per_row_est=bytes_per_row_est,
        effective_rows_est=effective_rows_est,
        min_rows_per_part=min_rows_per_part,
        target_partition_mem_mb=target_partition_mem_mb,
        partitioning_overhead_coef=partitioning_overhead_coef,
        max_partitions=max_partitions,
    )


def estimate_query_partitions(
    *,
    engine: Engine,
    dialect: SQLDialect,
    cte_prefix_sql: str,
    relation_sql: str,
    selected_sql_columns: Sequence[str],
    effective_rows_est: int,
    output_column_type_repr: dict[str, str],
    min_rows_per_part: int,
    target_partition_mem_mb: int,
    partitioning_overhead_coef: float,
    max_partitions: int,
) -> AutoPartitionEstimate:
    bytes_per_row_est: int | None = None
    if selected_sql_columns:
        try:
            sample_df = _sample_query_rows(
                engine=engine,
                dialect=dialect,
                cte_prefix_sql=cte_prefix_sql,
                relation_sql=relation_sql,
                selected_sql_columns=selected_sql_columns,
                sample_rows=SMART_BPR_SAMPLE_ROWS,
            )
        except Exception:
            sample_df = pd.DataFrame()
        bytes_per_row_est = _estimate_from_dataframe(
            sample_df,
            safety_coef=QUERY_BPR_SAFETY_COEF,
        )

    if bytes_per_row_est is None:
        heuristic_total = sum(
            _heuristic_col_width(None, type_repr) for type_repr in output_column_type_repr.values()
        )
        bytes_per_row_est = _with_safety(
            heuristic_total or 1024.0,
            safety_coef=QUERY_BPR_SAFETY_COEF,
        )

    return _finalize_estimate(
        dialect_name=dialect.name.lower(),
        bytes_per_row_est=bytes_per_row_est,
        effective_rows_est=effective_rows_est,
        min_rows_per_part=min_rows_per_part,
        target_partition_mem_mb=target_partition_mem_mb,
        partitioning_overhead_coef=partitioning_overhead_coef,
        max_partitions=max_partitions,
    )
