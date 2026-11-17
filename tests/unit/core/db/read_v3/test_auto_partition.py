from __future__ import annotations

import math
from types import SimpleNamespace

import pandas as pd
import sqlalchemy as sa

from core.db.read_v3._auto_partition import (
    DEFAULT_VARCHAR_BYTES,
    _table_bytes_and_rows,
    estimate_query_partitions,
    estimate_table_bytes_per_row,
    estimate_table_partitions,
)
from core.db.read_v3.dialects.clickhouse import ClickHouseDialect
from core.db.read_v3.dialects.postgres import PostgresDialect

import config


class _FakeDialect:
    def __init__(self, name: str = "sqlite") -> None:
        self.name = name

    def full_table_name(self, table: str, schema: str | None) -> str:
        return f"{schema}.{table}" if schema else table


class _FakeEngine:
    dialect = SimpleNamespace(name="sqlite")
    url = SimpleNamespace(database="db")


def test_table_bytes_and_rows_uses_dialect_quoted_full_table_name_for_count_queries() -> None:
    captured: dict[str, str] = {}

    class _Result:
        def scalar(self) -> int:
            return 7

    class _Connection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def execute(self, statement, *_args, **_kwargs) -> _Result:
            captured["sql"] = statement.text
            return _Result()

    class _EngineWithConnection(_FakeEngine):
        def connect(self) -> _Connection:
            return _Connection()

    class _QuotedDialect(_FakeDialect):
        def full_table_name(self, table: str, schema: str | None) -> str:
            return '"my schema"."select"'

    total_bytes, total_rows = _table_bytes_and_rows(
        _EngineWithConnection(),
        _QuotedDialect("sqlite"),
        table_name="select",
        schema="my schema",
    )

    assert captured["sql"] == 'SELECT COUNT(*) FROM "my schema"."select"'
    assert total_rows == 7
    assert total_bytes == 7 * DEFAULT_VARCHAR_BYTES


def test_estimate_table_partitions_uses_metadata_path(monkeypatch) -> None:
    monkeypatch.setattr(
        "core.db.read_v3._auto_partition._column_avg_bytes_from_metadata",
        lambda *_args, **_kwargs: {"id": 8.0, "payload": 120.0},
    )
    monkeypatch.setattr(
        "core.db.read_v3._auto_partition._table_bytes_and_rows",
        lambda *_args, **_kwargs: (128_000_000, 1_000_000),
    )
    monkeypatch.setattr(
        "core.db.read_v3._auto_partition._sample_table_rows",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("sample path must not be used")),
    )

    estimate = estimate_table_partitions(
        engine=_FakeEngine(),
        dialect=_FakeDialect("postgresql"),
        table_name="events",
        schema=None,
        selected_columns=["id", "payload"],
        columns_info=[
            {"name": "id", "type": sa.Integer()},
            {"name": "payload", "type": sa.Text()},
        ],
        effective_rows_est=50_000,
        min_rows_per_part=config.DASK_PARTITIONING.MIN_ROWS_PER_PART,
        target_partition_mem_mb=config.DASK_PARTITIONING.TARGET_PARTITION_MEM_MB,
        partitioning_overhead_coef=config.DASK_PARTITIONING.OVERHEAD_COEF,
        max_partitions=config.DASK_PARTITIONING.MAX_PARTITIONS,
    )

    assert estimate.bytes_per_row_est == 178
    assert estimate.effective_rows_est == 50_000
    assert estimate.dialect == "postgresql"
    assert estimate.npartitions == 1


def test_estimate_table_partitions_falls_back_to_type_heuristic_when_sample_is_empty(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "core.db.read_v3._auto_partition._column_avg_bytes_from_metadata",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "core.db.read_v3._auto_partition._table_bytes_and_rows",
        lambda *_args, **_kwargs: (0, None),
    )
    monkeypatch.setattr(
        "core.db.read_v3._auto_partition._sample_table_rows",
        lambda *_args, **_kwargs: pd.DataFrame(),
    )

    estimate = estimate_table_partitions(
        engine=_FakeEngine(),
        dialect=_FakeDialect("sqlite"),
        table_name="events",
        schema=None,
        selected_columns=["id", "payload"],
        columns_info=[
            {"name": "id", "type": sa.Integer()},
            {"name": "payload", "type": sa.String(length=200)},
        ],
        effective_rows_est=20_000,
        min_rows_per_part=config.DASK_PARTITIONING.MIN_ROWS_PER_PART,
        target_partition_mem_mb=config.DASK_PARTITIONING.TARGET_PARTITION_MEM_MB,
        partitioning_overhead_coef=config.DASK_PARTITIONING.OVERHEAD_COEF,
        max_partitions=config.DASK_PARTITIONING.MAX_PARTITIONS,
    )

    assert estimate.bytes_per_row_est == 94
    assert estimate.effective_bytes_est == 1_880_000
    assert estimate.npartitions == 2
    assert estimate.rows_per_part == 10_000


def test_estimate_query_partitions_uses_sample_and_respects_effective_limit(monkeypatch) -> None:
    sample_df = pd.DataFrame(
        {
            "id": [1, 2, 3],
            "payload": ["a" * 1000, "b" * 1000, "c" * 1000],
        }
    )
    monkeypatch.setattr(
        "core.db.read_v3._auto_partition._sample_query_rows",
        lambda *_args, **_kwargs: sample_df,
    )

    estimate = estimate_query_partitions(
        engine=_FakeEngine(),
        dialect=_FakeDialect("sqlite"),
        cte_prefix_sql="",
        relation_sql="FROM user_query",
        selected_sql_columns=["id", "payload"],
        effective_rows_est=17,
        output_column_type_repr={"id": "INTEGER", "payload": "TEXT"},
        min_rows_per_part=config.DASK_PARTITIONING.MIN_ROWS_PER_PART,
        target_partition_mem_mb=config.DASK_PARTITIONING.TARGET_PARTITION_MEM_MB,
        partitioning_overhead_coef=config.DASK_PARTITIONING.OVERHEAD_COEF,
        max_partitions=config.DASK_PARTITIONING.MAX_PARTITIONS,
    )

    assert estimate.effective_rows_est == 17
    assert estimate.bytes_per_row_est > 1_000
    assert estimate.npartitions == 1


def test_estimate_partitions_handles_zero_and_small_row_cases(monkeypatch) -> None:
    monkeypatch.setattr(
        "core.db.read_v3._auto_partition._sample_query_rows",
        lambda *_args, **_kwargs: pd.DataFrame(),
    )

    zero_rows = estimate_query_partitions(
        engine=_FakeEngine(),
        dialect=_FakeDialect("sqlite"),
        cte_prefix_sql="",
        relation_sql="FROM user_query",
        selected_sql_columns=["payload"],
        effective_rows_est=0,
        output_column_type_repr={"payload": "TEXT"},
        min_rows_per_part=config.DASK_PARTITIONING.MIN_ROWS_PER_PART,
        target_partition_mem_mb=config.DASK_PARTITIONING.TARGET_PARTITION_MEM_MB,
        partitioning_overhead_coef=config.DASK_PARTITIONING.OVERHEAD_COEF,
        max_partitions=config.DASK_PARTITIONING.MAX_PARTITIONS,
    )
    small_rows = estimate_query_partitions(
        engine=_FakeEngine(),
        dialect=_FakeDialect("sqlite"),
        cte_prefix_sql="",
        relation_sql="FROM user_query",
        selected_sql_columns=["payload"],
        effective_rows_est=3,
        output_column_type_repr={"payload": "TEXT"},
        min_rows_per_part=config.DASK_PARTITIONING.MIN_ROWS_PER_PART,
        target_partition_mem_mb=config.DASK_PARTITIONING.TARGET_PARTITION_MEM_MB,
        partitioning_overhead_coef=config.DASK_PARTITIONING.OVERHEAD_COEF,
        max_partitions=config.DASK_PARTITIONING.MAX_PARTITIONS,
    )

    assert zero_rows.npartitions == 1
    assert zero_rows.effective_bytes_est == 0
    assert small_rows.npartitions == 1
    assert small_rows.npartitions <= small_rows.effective_rows_est


class _CatalogEngine:
    """Engine stub answering every statement with the same catalog rows."""

    def __init__(self, rows: list[SimpleNamespace], database: str | None = "db") -> None:
        self.rows = rows
        self.url = SimpleNamespace(database=database)
        self.statements: list[tuple[str, dict]] = []

    def connect(self):
        engine = self

        class _Connection:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb) -> bool:
                return False

            def execute(self, statement, params=None):
                engine.statements.append((statement.text, dict(params or {})))
                return SimpleNamespace(fetchall=lambda: list(engine.rows))

        return _Connection()


# Per-column uncompressed bytes of the 49.69M-row sandbox table: 4 String, 3 Int64, 3 Float64.
_SANDBOX_ROWS = 49_690_000
_SANDBOX_COLUMN_BYTES = {
    "tovarnaia_gruppa": ("String", 1_757_149_200),
    "summa_po_preiskurantu": ("Float64", 397_520_000),
    "nomer_cheka": ("Int64", 397_520_000),
    "vremia_pokupki": ("String", 993_800_000),
    "nomer_karty": ("String", 325_808_425),
    "kod_tovara": ("Int64", 397_520_000),
    "naimenovanie_tovara": ("String", 3_080_199_100),
    "nomer_kassy": ("Int64", 397_520_000),
    "kolichestvo": ("Float64", 397_520_000),
    "summa_k_oplate": ("Float64", 397_520_000),
}


def test_clickhouse_width_uses_column_bytes_of_wide_parts(monkeypatch) -> None:
    engine = _CatalogEngine(
        [
            SimpleNamespace(column=name, uncompressed_bytes=size, r=_SANDBOX_ROWS)
            for name, (_type, size) in _SANDBOX_COLUMN_BYTES.items()
        ]
    )
    monkeypatch.setattr(
        "core.db.read_v3._auto_partition._table_bytes_and_rows",
        lambda *_args, **_kwargs: (8_542_076_725, _SANDBOX_ROWS),
    )
    monkeypatch.setattr(
        "core.db.read_v3._auto_partition._sample_table_rows",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("catalog must be used")),
    )

    bytes_per_row = estimate_table_bytes_per_row(
        engine=engine,
        dialect=ClickHouseDialect(),
        table_name="arustamov_full",
        schema=None,
        selected_columns=list(_SANDBOX_COLUMN_BYTES),
        columns_info=[
            {"name": name, "type": type_name}
            for name, (type_name, _size) in _SANDBOX_COLUMN_BYTES.items()
        ],
    )

    sql, params = engine.statements[0]
    assert "sum(column_data_uncompressed_bytes)" in sql
    assert "part_type = 'Wide'" in sql
    assert params == {"db": "db", "tbl": "arustamov_full"}
    # 171.9 uncompressed bytes per row, safety coefficient 1.2 and 24 bytes of row overhead;
    # the part-level data_uncompressed_bytes per column used to give 2087.
    assert bytes_per_row == 231


def test_clickhouse_width_without_wide_parts_falls_back_to_sample(monkeypatch) -> None:
    engine = _CatalogEngine([])
    sample = pd.DataFrame({"id": [1, 2, 3, 4]})
    monkeypatch.setattr(
        "core.db.read_v3._auto_partition._table_bytes_and_rows",
        lambda *_args, **_kwargs: (40, 5),
    )
    monkeypatch.setattr(
        "core.db.read_v3._auto_partition._sample_table_rows",
        lambda *_args, **_kwargs: sample,
    )

    bytes_per_row = estimate_table_bytes_per_row(
        engine=engine,
        dialect=ClickHouseDialect(),
        table_name="small",
        schema="analytics",
        selected_columns=["id"],
        columns_info=[{"name": "id", "type": "Int64"}],
    )

    assert engine.statements[0][1] == {"db": "analytics", "tbl": "small"}
    sample_bytes_per_row = sample.memory_usage(deep=True).sum() / len(sample)
    assert bytes_per_row == math.ceil(sample_bytes_per_row * 1.2 + 24)


def test_postgres_width_uses_pg_stats_of_the_resolved_table(monkeypatch) -> None:
    engine = _CatalogEngine(
        [
            SimpleNamespace(column_name="id", avg_width=8),
            # Inherited statistics come first (ORDER BY inherited DESC) and win.
            SimpleNamespace(column_name="payload", avg_width=120),
            SimpleNamespace(column_name="payload", avg_width=60),
            SimpleNamespace(column_name="note", avg_width=None),
        ]
    )
    monkeypatch.setattr(
        "core.db.read_v3._auto_partition._table_bytes_and_rows",
        lambda *_args, **_kwargs: (0, None),
    )
    monkeypatch.setattr(
        "core.db.read_v3._auto_partition._sample_table_rows",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("catalog must be used")),
    )

    bytes_per_row = estimate_table_bytes_per_row(
        engine=engine,
        dialect=PostgresDialect(),
        table_name="Events",
        schema=None,
        selected_columns=["id", "payload", "note"],
        columns_info=[
            {"name": "id", "type": sa.BigInteger()},
            {"name": "payload", "type": sa.Text()},
            {"name": "note", "type": sa.Text()},
        ],
    )

    sql, params = engine.statements[0]
    assert "CAST(:fq AS regclass)" in sql
    assert "ORDER BY s.attname, s.inherited DESC" in sql
    # Without a schema the quoted name resolves through search_path.
    assert params == {"fq": '"Events"'}
    # 8 + 120 + 64 (TEXT heuristic for the column without avg_width).
    assert bytes_per_row == math.ceil((8 + 120 + DEFAULT_VARCHAR_BYTES) * 1.2 + 24)
