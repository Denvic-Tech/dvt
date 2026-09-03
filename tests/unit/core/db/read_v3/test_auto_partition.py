from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import sqlalchemy as sa

from core.db.read_v3._auto_partition import (
    DEFAULT_VARCHAR_BYTES,
    _table_bytes_and_rows,
    estimate_query_partitions,
    estimate_table_partitions,
)

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
