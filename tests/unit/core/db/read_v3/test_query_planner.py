from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from core.db.read_v3.dialects.oracle import OracleDialect
from core.db.read_v3.errors import ReadV3ConfigError
from core.db.read_v3.models import PartitionStrategy, ReadSegment, SegmentDivision
from core.db.read_v3.planner.query import QueryReadPlanner

import config


STRICT_PARTITIONING_KWARGS = {
    "min_rows_per_partition": config.DASK_PARTITIONING.MIN_ROWS_PER_PART,
    "target_partition_mem_mb": config.DASK_PARTITIONING.TARGET_PARTITION_MEM_MB,
    "partitioning_overhead_coef": config.DASK_PARTITIONING.OVERHEAD_COEF,
    "max_partitions": config.DASK_PARTITIONING.MAX_PARTITIONS,
}


class _FakeOracleEngine:
    dialect = type("_Dialect", (), {"name": "oracle"})()


class _FakeClickHouseEngine:
    dialect = type("_Dialect", (), {"name": "clickhouse"})()


class _FakeMssqlEngine:
    dialect = type("_Dialect", (), {"name": "mssql"})()


def test_query_planner_uses_describe_columns_when_clickhouse_zero_row_df_has_no_columns(
    monkeypatch,
) -> None:
    def _fake_read_sql_df(_engine, sql):
        rendered_sql = str(sql)
        if "WHERE 1=0" in rendered_sql:
            return pd.DataFrame()
        if "AS sample_value" in rendered_sql:
            return pd.DataFrame({"sample_value": [1]})
        raise AssertionError(f"Unexpected SQL in planner stub: {rendered_sql}")

    monkeypatch.setattr("core.db.read_v3.planner.query.read_sql_df", _fake_read_sql_df)
    monkeypatch.setattr(
        "core.db.read_v3.planner.query.describe_query_columns",
        lambda *_args, **_kwargs: [("id", "Int64"), ("label", "Nullable(String)")],
    )
    monkeypatch.setattr(
        "core.db.read_v3.planner.query.query_row_stats",
        lambda **_kwargs: (1, 2, 2, 2),
    )
    monkeypatch.setattr(
        "core.db.read_v3.planner.query.choose_partition_strategy",
        lambda **_kwargs: SimpleNamespace(strategy=PartitionStrategy.HASH, reason="test"),
    )

    plan = QueryReadPlanner().build_plan(
        engine=_FakeClickHouseEngine(),
        query="SELECT id, label FROM events",
        partition_col="id",
        npartitions=2,
        **STRICT_PARTITIONING_KWARGS,
    )

    assert plan.output_columns == ["id", "label"]
    assert plan.partition_key_name == "id"
    assert plan.output_column_type_repr == {
        "id": "Int64",
        "label": "Nullable(String)",
    }


def test_query_planner_rejects_mssql_batch_scripts_before_db_access() -> None:
    with pytest.raises(
        ReadV3ConfigError,
        match="supports a single SELECT query or top-level WITH \\.\\.\\. SELECT",
    ):
        QueryReadPlanner().build_plan(
            engine=_FakeMssqlEngine(),
            query="DECLARE @id INT = 1; SELECT @id AS id",
            partition_col="id",
            **STRICT_PARTITIONING_KWARGS,
        )


@pytest.mark.skip("TODO: FIX it")
def test_query_planner_uses_oracle_result_column_quoting_for_query_columns(monkeypatch) -> None:
    captured_stats: dict[str, str] = {}
    captured_hash: dict[str, str] = {}

    def _fake_read_sql_query(sql, *_args, **_kwargs):
        rendered_sql = str(sql)
        if "WHERE 1=0" in rendered_sql:
            return pd.DataFrame(columns=["period", "Source", "Kontragent"])
        if "AS sample_value" in rendered_sql:
            return pd.DataFrame({"sample_value": ["alpha"]})
        raise AssertionError(f"Unexpected SQL in planner stub: {rendered_sql}")

    def _fake_describe_query_columns(*_args, **_kwargs):
        return [
            ("PERIOD", "VARCHAR2"),
            ("Source", "VARCHAR2"),
            ("Kontragent", "VARCHAR2"),
        ]

    def _fake_query_row_stats(*, key_sql, **_kwargs):
        captured_stats["key_sql"] = key_sql
        return ("alpha", "omega", 10, 10)

    def _fake_infer_npartitions(*_args, **_kwargs):
        return 4

    def _fake_build_hash_segments(*, key_sql, hash_sql, **_kwargs):
        captured_hash["key_sql"] = key_sql
        captured_hash["hash_sql"] = hash_sql
        return (
            [
                ReadSegment(
                    label="h0",
                    predicate_sql=f"{hash_sql} = 0",
                    order_by_sql=f"ORDER BY {key_sql} ASC",
                    division=SegmentDivision(start=0, end=1, include_end=False),
                    strategy=PartitionStrategy.HASH,
                )
            ],
            (0, 1),
            1,
        )

    monkeypatch.setattr("core.db.read_v3.planner.query.resolve_dialect", lambda _engine: OracleDialect())
    monkeypatch.setattr(
        "core.db.read_v3.planner.query.read_sql_df",
        lambda _engine, sql: _fake_read_sql_query(sql),
    )
    monkeypatch.setattr(
        "core.db.read_v3.planner.query.describe_query_columns",
        _fake_describe_query_columns,
    )
    monkeypatch.setattr(
        "core.db.read_v3.planner.query.choose_partition_strategy",
        lambda **_kwargs: SimpleNamespace(strategy=PartitionStrategy.HASH, reason="test"),
    )
    monkeypatch.setattr("core.db.read_v3.planner.query.query_row_stats", _fake_query_row_stats)
    monkeypatch.setattr("core.db.read_v3.planner.query.infer_npartitions", _fake_infer_npartitions)
    monkeypatch.setattr("core.db.read_v3.planner.query.build_hash_segments", _fake_build_hash_segments)

    plan = QueryReadPlanner().build_plan(
        engine=_FakeOracleEngine(),
        query="""SELECT '2026-01' AS PERIOD, 'alpha' AS "Source", 'beta' AS "Kontragent" FROM dual""",
        partition_col="period",
        **STRICT_PARTITIONING_KWARGS,
    )

    assert captured_stats["key_sql"] == '"PERIOD"'
    assert captured_hash["key_sql"] == '"PERIOD"'
    assert '"PERIOD"' in captured_hash["hash_sql"]
    assert plan.select_exprs[:3] == ['"PERIOD"', '"Source"', '"Kontragent"']
    assert len(plan.select_exprs) == 4
    assert 'TO_CHAR("PERIOD")' in plan.select_exprs[3]
    assert 'AS "__dvt_partition_bucket"' in plan.select_exprs[3]
    assert plan.partition_key_name == "PERIOD"
    assert plan.partition_key_sql_name == "PERIOD"
    assert plan.output_columns == ["PERIOD", "Source", "Kontragent"]
    assert plan.output_column_sql_names == {
        "PERIOD": "PERIOD",
        "Source": "Source",
        "Kontragent": "Kontragent",
    }


def test_query_planner_stringifies_mssql_uniqueidentifier_and_binary_outputs(monkeypatch) -> None:
    def _fake_read_sql_df(_engine, sql):
        rendered_sql = str(sql)
        if "WHERE 1=0" in rendered_sql:
            return pd.DataFrame(columns=["id", "guid_col", "bin_col"])
        if "AS sample_value" in rendered_sql:
            return pd.DataFrame({"sample_value": [1]})
        raise AssertionError(f"Unexpected SQL in planner stub: {rendered_sql}")

    monkeypatch.setattr("core.db.read_v3.planner.query.read_sql_df", _fake_read_sql_df)
    monkeypatch.setattr(
        "core.db.read_v3.planner.query.describe_query_columns",
        lambda *_args, **_kwargs: [
            ("id", "INT"),
            ("guid_col", "UNIQUEIDENTIFIER"),
            ("bin_col", "VARBINARY(16)"),
        ],
    )
    monkeypatch.setattr(
        "core.db.read_v3.planner.query.query_row_stats",
        lambda **_kwargs: (1, 2, 2, 2),
    )
    monkeypatch.setattr(
        "core.db.read_v3.planner.query.choose_partition_strategy",
        lambda **_kwargs: SimpleNamespace(strategy=PartitionStrategy.HASH, reason="test"),
    )
    monkeypatch.setattr(
        "core.db.read_v3.planner.query.build_hash_segments",
        lambda **_kwargs: (
            [
                ReadSegment(
                    label="h0",
                    predicate_sql="1=1",
                    order_by_sql="ORDER BY [id] ASC",
                    division=SegmentDivision(start=0, end=1, include_end=False),
                    strategy=PartitionStrategy.HASH,
                )
            ],
            (0, 1),
            1,
        ),
    )

    plan = QueryReadPlanner().build_plan(
        engine=_FakeMssqlEngine(),
        query="SELECT id, guid_col, bin_col FROM dbo.events",
        partition_col="id",
        npartitions=1,
        **STRICT_PARTITIONING_KWARGS,
    )

    assert plan.select_exprs[:3] == [
        "[id]",
        "CAST([guid_col] AS NVARCHAR(MAX)) AS [guid_col]",
        "CONVERT(VARCHAR(MAX), [bin_col], 2) AS [bin_col]",
    ]
    assert plan.output_column_select_exprs == {
        "id": "[id]",
        "guid_col": "CAST([guid_col] AS NVARCHAR(MAX)) AS [guid_col]",
        "bin_col": "CONVERT(VARCHAR(MAX), [bin_col], 2) AS [bin_col]",
    }
