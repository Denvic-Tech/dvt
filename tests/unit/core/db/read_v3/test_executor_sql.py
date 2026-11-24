from __future__ import annotations

import threading
from datetime import datetime, timedelta
from decimal import Decimal

import pandas as pd
import pytest
import sqlalchemy as sa
from sqlalchemy import text

from core.db.read_v3.dask import frame_from_executor
from core.db.read_v3.datetime_precision import ReadV3DateTimePrecision
from core.db.read_v3.embedded_query import normalize_mssql_query_for_embedding
from core.db.read_v3.dialects.mssql import MssqlDialect
from core.db.read_v3.dialects.oracle import OracleDialect
from core.db.read_v3.errors import ReadV3ConfigError, ReadV3ExecutionError
from core.db.read_v3.executors.sql import SQLReadExecutor
from core.db.read_v3.models import (
    PartitionStrategy,
    ReadMode,
    ReadSegment,
    ReadV3Plan,
    SegmentDivision,
    ValueKind,
)
from core.db.read_v3.resolver import resolve_executor, resolve_planner

import config


STRICT_PARTITIONING_KWARGS = {
    "min_rows_per_partition": config.DASK_PARTITIONING.MIN_ROWS_PER_PART,
    "target_partition_mem_mb": config.DASK_PARTITIONING.TARGET_PARTITION_MEM_MB,
    "partitioning_overhead_coef": config.DASK_PARTITIONING.OVERHEAD_COEF,
    "max_partitions": config.DASK_PARTITIONING.MAX_PARTITIONS,
}


class _FakeOracleEngine:
    dialect = type("_Dialect", (), {"name": "oracle"})()


def _seed(engine: sa.Engine, rows: int = 32) -> None:
    base_ts = datetime(2026, 1, 1, 0, 0, 0)
    payload = []
    for idx in range(1, rows + 1):
        payload.append(
            {
                "id": idx,
                "category": f"cat-{idx % 3}",
                "created_at": base_ts + timedelta(minutes=idx),
            }
        )

    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS read_v3_exec_test"))
        conn.execute(
            text(
                """
                CREATE TABLE read_v3_exec_test (
                    id INTEGER PRIMARY KEY,
                    category TEXT,
                    created_at TEXT
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO read_v3_exec_test (id, category, created_at)
                VALUES (:id, :category, :created_at)
                """
            ),
            payload,
        )


def test_executor_raises_when_segment_exceeds_max_rows(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'bounded.sqlite'}")
    _seed(engine, rows=20)

    planner = resolve_planner(mode="table")
    plan = planner.build_plan(
        engine=engine,
        table_name="read_v3_exec_test",
        columns=["id", "category"],
        partition_col="id",
        npartitions=1,
        max_rows_per_partition=5,
        **STRICT_PARTITIONING_KWARGS,
    )
    executor = resolve_executor(engine)

    with pytest.raises(
        ReadV3ExecutionError,
        match=r"Segment 'range_0' exceeded max_rows_per_partition=5 \(rows_read=6\)",
    ):
        executor.load_partition(plan, plan.segments[0])


def test_executor_drops_helper_columns_from_output(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'helpers.sqlite'}")
    _seed(engine, rows=12)

    planner = resolve_planner(mode="table")
    plan = planner.build_plan(
        engine=engine,
        table_name="read_v3_exec_test",
        columns=["category"],
        partition_col="id",
        npartitions=4,
        max_rows_per_partition=100,
        **STRICT_PARTITIONING_KWARGS,
    )
    executor = resolve_executor(engine)

    df = executor.load_partition(plan, plan.segments[0])
    assert list(df.columns) == ["category"]
    assert plan.partition_key_alias not in df.columns


def test_mssql_cap_rows_sql_uses_top_clause() -> None:
    sql = "SELECT * FROM [dbo].[events] ORDER BY [id]"
    wrapped = MssqlDialect().cap_rows_sql(sql, 3)
    assert wrapped == (
        "SELECT TOP (3) * FROM "
        "(SELECT * FROM [dbo].[events] ORDER BY [id] OFFSET 0 ROWS) __dvt_cap"
    )


def test_mssql_cap_rows_sql_handles_cte_query() -> None:
    sql = "WITH user_query AS (SELECT [id] FROM [dbo].[events]) SELECT [id] FROM user_query"
    wrapped = MssqlDialect().cap_rows_sql(sql, 2)
    assert wrapped == (
        "WITH user_query AS (SELECT [id] FROM [dbo].[events]) "
        "SELECT TOP (2) [id] FROM user_query"
    )


def test_normalize_mssql_query_for_embedding_adds_offset_for_top_level_order_by() -> None:
    sql = "SELECT [id], [created_at] FROM [dbo].[events] ORDER BY [created_at]"

    normalized = normalize_mssql_query_for_embedding(sql)

    assert normalized == (
        "SELECT [id], [created_at] FROM [dbo].[events] "
        "ORDER BY [created_at] OFFSET 0 ROWS"
    )


def test_normalize_mssql_query_for_embedding_ignores_window_order_by() -> None:
    sql = (
        "SELECT [id], ROW_NUMBER() OVER (PARTITION BY [group_id] ORDER BY [created_at]) AS [rn] "
        "FROM [dbo].[events]"
    )

    normalized = normalize_mssql_query_for_embedding(sql)

    assert normalized == sql


def test_normalize_mssql_query_for_embedding_keeps_existing_top_clause() -> None:
    sql = "SELECT TOP (5) [id] FROM [dbo].[events] ORDER BY [created_at]"

    normalized = normalize_mssql_query_for_embedding(sql)

    assert normalized == sql


def test_normalize_mssql_query_for_embedding_keeps_existing_offset_clause() -> None:
    sql = "SELECT [id] FROM [dbo].[events] ORDER BY [created_at] OFFSET 0 ROWS"

    normalized = normalize_mssql_query_for_embedding(sql)

    assert normalized == sql


def test_oracle_cap_rows_sql_uses_valid_alias() -> None:
    sql = 'SELECT "id" FROM "events" ORDER BY "id"'
    wrapped = OracleDialect().cap_rows_sql(sql, 5)
    assert wrapped == (
        'SELECT * FROM (SELECT "id" FROM "events" ORDER BY "id") '
        "dvt_cap OFFSET 0 ROWS FETCH NEXT 5 ROWS ONLY"
    )


def test_oracle_quote_result_column_quotes_mixed_case_simple_identifier() -> None:
    assert OracleDialect().quote_result_column("Source") == '"Source"'


def test_oracle_quote_result_column_keeps_simple_lowercase_identifier_unquoted() -> None:
    assert OracleDialect().quote_result_column("category") == "category"


def test_oracle_quote_result_column_keeps_prequoted_identifier() -> None:
    assert OracleDialect().quote_result_column('"Source"') == '"Source"'


def test_build_meta_uses_sample_row_dtypes(monkeypatch) -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    executor = SQLReadExecutor(engine)
    calls: list[str] = []

    def _fake_read_sql_query(sql, *_args, **_kwargs):
        rendered_sql = str(sql).lower()
        calls.append(rendered_sql)
        if "__dvt_cap" in rendered_sql:
            return pd.DataFrame(
                {
                    "id": pd.Series([1], dtype="int64"),
                    "balance": pd.Series([100.25], dtype="float64"),
                    "is_deleted": pd.Series([False], dtype="bool"),
                    "created_at": pd.to_datetime(["2026-01-01 10:00:00"]),
                    "email": pd.Series(["user@example.com"], dtype="object"),
                }
            )
        if "where 1=0" in rendered_sql:
            return pd.DataFrame(
                {column: pd.Series(dtype="object") for column in ("id", "balance", "is_deleted", "created_at", "email")}
            )
        raise AssertionError(f"Unexpected SQL in test stub: {sql!r}")

    monkeypatch.setattr(executor.sql_runner, "query_df", _fake_read_sql_query)

    plan = ReadV3Plan(
        mode=ReadMode.TABLE,
        dialect="sqlite",
        cte_prefix_sql=None,
        relation_sql="FROM users",
        select_exprs=["id", "balance", "is_deleted", "created_at", "email"],
        output_columns=["id", "balance", "is_deleted", "created_at", "email"],
        partition_key_name="id",
        partition_key_kind=ValueKind.NUMERIC,
        strategy=PartitionStrategy.RANGE,
        segments=[
            ReadSegment(
                label="p0",
                predicate_sql="id >= 1 AND id <= 10",
                order_by_sql="ORDER BY id ASC",
                division=SegmentDivision(start=1, end=10, include_end=True),
                strategy=PartitionStrategy.RANGE,
            )
        ],
        divisions=(1, 10),
        max_rows_per_partition=100,
    )

    meta = executor.build_meta(plan)

    assert pd.api.types.is_integer_dtype(meta["id"].dtype)
    assert pd.api.types.is_float_dtype(meta["balance"].dtype)
    assert pd.api.types.is_bool_dtype(meta["is_deleted"].dtype)
    assert pd.api.types.is_datetime64_any_dtype(meta["created_at"].dtype)
    assert not pd.api.types.is_string_dtype(meta["id"].dtype)
    assert not any("where 1=0" in call for call in calls)


def test_build_meta_uses_oracle_result_column_quoting(monkeypatch) -> None:
    executor = SQLReadExecutor(_FakeOracleEngine(), dialect=OracleDialect())
    captured_sql: list[str] = []

    def _fake_read_sql_query(sql, *_args, **_kwargs):
        captured_sql.append(str(sql))
        return pd.DataFrame(
            {
                "period": pd.to_datetime(["2026-01-01"]),
                "Source": pd.Series(["alpha"], dtype="object"),
                "Kontragent": pd.Series(["beta"], dtype="object"),
            }
        )

    monkeypatch.setattr(executor.sql_runner, "query_df", _fake_read_sql_query)

    plan = ReadV3Plan(
        mode=ReadMode.QUERY,
        dialect="oracle",
        cte_prefix_sql='WITH user_query AS (SELECT 1 AS PERIOD, 2 AS "Source", 3 AS "Kontragent" FROM dual)',
        relation_sql="FROM user_query",
        select_exprs=['"PERIOD"', '"Source"', '"Kontragent"'],
        output_columns=["PERIOD", "Source", "Kontragent"],
        partition_key_name="PERIOD",
        partition_key_kind=ValueKind.STRING,
        strategy=PartitionStrategy.HASH,
        segments=[
            ReadSegment(
                label="h0",
                predicate_sql="1=1",
                order_by_sql='ORDER BY "PERIOD" ASC',
                division=SegmentDivision(start=0, end=1, include_end=False),
                strategy=PartitionStrategy.HASH,
            )
        ],
        divisions=(0, 1),
        max_rows_per_partition=100,
        output_column_kinds={
            "PERIOD": ValueKind.STRING,
            "Source": ValueKind.STRING,
            "Kontragent": ValueKind.STRING,
        },
        output_column_sql_names={
            "PERIOD": "PERIOD",
            "Source": "Source",
            "Kontragent": "Kontragent",
        },
        partition_key_sql_name="PERIOD",
        index_column_name="PERIOD",
    )

    meta = executor.build_meta(plan)

    assert list(meta.columns) == ["PERIOD", "Source", "Kontragent"]
    assert str(meta["PERIOD"].dtype) == "string"
    assert len(captured_sql) == 1
    assert 'SELECT PERIOD, "Source", "Kontragent" FROM user_query' in captured_sql[0]


def test_build_meta_projects_case_drifted_oracle_columns_to_exact_public_names(monkeypatch) -> None:
    executor = SQLReadExecutor(_FakeOracleEngine(), dialect=OracleDialect())

    def _fake_read_sql_query(sql, *_args, **_kwargs):
        return pd.DataFrame(
            {
                "period": pd.to_datetime(["2026-01-01"]),
                "article": pd.Series(["A-1"], dtype="object"),
                "Source": pd.Series(["crm"], dtype="object"),
            }
        )

    monkeypatch.setattr(executor.sql_runner, "query_df", _fake_read_sql_query)

    plan = ReadV3Plan(
        mode=ReadMode.QUERY,
        dialect="oracle",
        cte_prefix_sql='WITH user_query AS (SELECT DATE \'2026-01-01\' AS PERIOD, \'A-1\' AS ARTICLE, \'crm\' AS "Source" FROM dual)',
        relation_sql="FROM user_query",
        select_exprs=['"PERIOD"', '"ARTICLE"', '"Source"'],
        output_columns=["PERIOD", "ARTICLE", "Source"],
        partition_key_name="PERIOD",
        partition_key_kind=ValueKind.DATE,
        strategy=PartitionStrategy.HASH,
        segments=[
            ReadSegment(
                label="h0",
                predicate_sql="1=1",
                order_by_sql='ORDER BY "PERIOD" ASC',
                division=SegmentDivision(start=0, end=1, include_end=False),
                strategy=PartitionStrategy.HASH,
            )
        ],
        divisions=(0, 1),
        max_rows_per_partition=100,
        output_column_kinds={
            "PERIOD": ValueKind.DATE,
            "ARTICLE": ValueKind.STRING,
            "Source": ValueKind.STRING,
        },
        output_column_type_repr={
            "PERIOD": "DATE",
            "ARTICLE": "VARCHAR2",
            "Source": "VARCHAR2",
        },
        output_column_sql_names={
            "PERIOD": "PERIOD",
            "ARTICLE": "ARTICLE",
            "Source": "Source",
        },
        partition_key_sql_name="PERIOD",
        index_column_name="PERIOD",
    )

    meta = executor.build_meta(plan)

    assert list(meta.columns) == ["PERIOD", "ARTICLE", "Source"]
    assert str(meta["PERIOD"].dtype) == "datetime64[us]"
    assert meta["ARTICLE"].dtype.name == "string"
    assert meta["Source"].dtype.name == "string"


def test_load_partition_projects_case_drifted_oracle_columns_to_exact_public_names(monkeypatch) -> None:
    executor = SQLReadExecutor(_FakeOracleEngine(), dialect=OracleDialect())
    payload = pd.DataFrame(
        {
            "period": pd.to_datetime(["2026-01-01", "2026-01-02"]),
            "article": pd.Series(["A-1", "A-2"], dtype="object"),
            "Source": pd.Series(["crm", "erp"], dtype="object"),
            "__DVT_PARTITION_BUCKET": pd.Series([0, 0], dtype="int64"),
        }
    )
    monkeypatch.setattr(executor, "_read_sql_bounded", lambda *_args, **_kwargs: payload.copy())

    plan = ReadV3Plan(
        mode=ReadMode.QUERY,
        dialect="oracle",
        cte_prefix_sql='WITH user_query AS (SELECT DATE \'2026-01-01\' AS PERIOD, \'A-1\' AS ARTICLE, \'crm\' AS "Source" FROM dual)',
        relation_sql="FROM user_query",
        select_exprs=['"PERIOD"', '"ARTICLE"', '"Source"', '"__dvt_partition_bucket"'],
        output_columns=["PERIOD", "ARTICLE", "Source"],
        partition_key_name="PERIOD",
        partition_key_kind=ValueKind.DATE,
        strategy=PartitionStrategy.HASH,
        segments=[
            ReadSegment(
                label="h0",
                predicate_sql="1=1",
                order_by_sql='ORDER BY "PERIOD" ASC',
                division=SegmentDivision(start=0, end=1, include_end=False),
                strategy=PartitionStrategy.HASH,
            )
        ],
        divisions=(0, 1),
        max_rows_per_partition=100,
        output_column_kinds={
            "PERIOD": ValueKind.DATE,
            "ARTICLE": ValueKind.STRING,
            "Source": ValueKind.STRING,
        },
        output_column_type_repr={
            "PERIOD": "DATE",
            "ARTICLE": "VARCHAR2",
            "Source": "VARCHAR2",
        },
        output_column_sql_names={
            "PERIOD": "PERIOD",
            "ARTICLE": "ARTICLE",
            "Source": "Source",
        },
        partition_key_sql_name="PERIOD",
        index_column_name="__dvt_partition_bucket",
    )

    df = executor.load_partition(plan, plan.segments[0])

    assert list(df.columns) == ["PERIOD", "ARTICLE", "Source"]
    assert str(df["PERIOD"].dtype) == "datetime64[us]"
    assert df["ARTICLE"].dtype.name == "string"
    assert df["Source"].dtype.name == "string"
    assert not any(str(column).lower().startswith("__dvt_") for column in df.columns)


def test_build_meta_normalizes_mixed_datetime_tz(monkeypatch) -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    executor = SQLReadExecutor(engine)

    def _fake_read_sql_query(sql, *_args, **_kwargs):
        rendered_sql = str(sql).lower()
        if "__dvt_cap" in rendered_sql:
            return pd.DataFrame(
                {
                    "id": pd.Series([1], dtype="int64"),
                    "updated_at": pd.Series(["2026-01-01 10:00:00"], dtype="object"),
                    "dwh_src_ts": pd.Series(
                        [pd.Timestamp("2026-01-01 10:00:00+00:00")],
                        dtype="datetime64[ns, UTC]",
                    ),
                }
            )
        raise AssertionError(f"Unexpected SQL in test stub: {sql!r}")

    monkeypatch.setattr(executor.sql_runner, "query_df", _fake_read_sql_query)

    plan = ReadV3Plan(
        mode=ReadMode.TABLE,
        dialect="sqlite",
        cte_prefix_sql=None,
        relation_sql="FROM users",
        select_exprs=["id", "updated_at", "dwh_src_ts"],
        output_columns=["id", "updated_at", "dwh_src_ts"],
        partition_key_name="id",
        partition_key_kind=ValueKind.NUMERIC,
        strategy=PartitionStrategy.RANGE,
        segments=[
            ReadSegment(
                label="p0",
                predicate_sql="id >= 1 AND id <= 1",
                order_by_sql="ORDER BY id ASC",
                division=SegmentDivision(start=1, end=1, include_end=True),
                strategy=PartitionStrategy.RANGE,
            )
        ],
        divisions=(1, 1),
        max_rows_per_partition=100,
        output_column_kinds={
            "id": ValueKind.NUMERIC,
            "updated_at": ValueKind.DATETIME,
            "dwh_src_ts": ValueKind.DATETIME,
        },
    )

    meta = executor.build_meta(plan)

    assert str(meta["updated_at"].dtype) == "datetime64[us]"
    assert str(meta["dwh_src_ts"].dtype) == "datetime64[us]"
    assert not isinstance(meta["updated_at"].dtype, pd.DatetimeTZDtype)
    assert not isinstance(meta["dwh_src_ts"].dtype, pd.DatetimeTZDtype)


def test_load_partition_normalizes_mixed_datetime_tz(monkeypatch) -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    executor = SQLReadExecutor(engine)

    payload = pd.DataFrame(
        {
            "id": pd.Series([1, 2], dtype="int64"),
            "updated_at": pd.Series(
                [pd.Timestamp("2026-01-01 10:00:00"), pd.Timestamp("2026-01-01 10:01:00")]
            ),
            "dwh_src_ts": pd.Series(
                [
                    pd.Timestamp("2026-01-01 10:00:00+00:00"),
                    pd.Timestamp("2026-01-01 10:01:00+00:00"),
                ],
                dtype="datetime64[ns, UTC]",
            ),
        }
    )

    monkeypatch.setattr(executor, "_read_sql_bounded", lambda *_args, **_kwargs: payload.copy())

    plan = ReadV3Plan(
        mode=ReadMode.TABLE,
        dialect="sqlite",
        cte_prefix_sql=None,
        relation_sql="FROM users",
        select_exprs=["id", "updated_at", "dwh_src_ts"],
        output_columns=["id", "updated_at", "dwh_src_ts"],
        partition_key_name="id",
        partition_key_kind=ValueKind.NUMERIC,
        strategy=PartitionStrategy.RANGE,
        segments=[
            ReadSegment(
                label="p0",
                predicate_sql="id >= 1 AND id <= 2",
                order_by_sql="ORDER BY id ASC",
                division=SegmentDivision(start=1, end=2, include_end=True),
                strategy=PartitionStrategy.RANGE,
            )
        ],
        divisions=(1, 2),
        max_rows_per_partition=100,
        output_column_kinds={
            "id": ValueKind.NUMERIC,
            "updated_at": ValueKind.DATETIME,
            "dwh_src_ts": ValueKind.DATETIME,
        },
    )

    df = executor.load_partition(plan, plan.segments[0])

    assert str(df["updated_at"].dtype) == "datetime64[us]"
    assert str(df["dwh_src_ts"].dtype) == "datetime64[us]"
    assert not isinstance(df["updated_at"].dtype, pd.DatetimeTZDtype)
    assert not isinstance(df["dwh_src_ts"].dtype, pd.DatetimeTZDtype)


def test_load_partition_drops_uppercase_helper_column_in_range_mode(monkeypatch) -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    executor = SQLReadExecutor(engine)

    payload = pd.DataFrame(
        {
            "category": pd.Series(["cat-1"], dtype="object"),
            "__DVT_PARTITION_KEY": pd.Series([1], dtype="int64"),
        }
    )
    monkeypatch.setattr(executor, "_read_sql_bounded", lambda *_args, **_kwargs: payload.copy())

    plan = ReadV3Plan(
        mode=ReadMode.TABLE,
        dialect="sqlite",
        cte_prefix_sql=None,
        relation_sql="FROM users",
        select_exprs=["category", "__dvt_partition_key"],
        output_columns=["category"],
        partition_key_name="id",
        partition_key_kind=ValueKind.NUMERIC,
        strategy=PartitionStrategy.RANGE,
        segments=[
            ReadSegment(
                label="p0",
                predicate_sql="1=1",
                order_by_sql="ORDER BY id ASC",
                division=SegmentDivision(start=1, end=1, include_end=True),
                strategy=PartitionStrategy.RANGE,
            )
        ],
        divisions=(1, 1),
        max_rows_per_partition=100,
        index_column_name="__dvt_partition_key",
    )

    df = executor.load_partition(plan, plan.segments[0])

    assert list(df.columns) == ["category"]
    assert not any(str(column).lower().startswith("__dvt_") for column in df.columns)


def test_load_partition_drops_uppercase_helper_columns_in_hash_mode(monkeypatch) -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    executor = SQLReadExecutor(engine)

    payload = pd.DataFrame(
        {
            "id": pd.Series([10], dtype="int64"),
            "__DVT_PARTITION_BUCKET": pd.Series([0], dtype="int64"),
            "__DVT_PARTITION_KEY": pd.Series([10], dtype="int64"),
        }
    )
    monkeypatch.setattr(executor, "_read_sql_bounded", lambda *_args, **_kwargs: payload.copy())

    plan = ReadV3Plan(
        mode=ReadMode.TABLE,
        dialect="sqlite",
        cte_prefix_sql=None,
        relation_sql="FROM users",
        select_exprs=["id", "__dvt_partition_bucket", "__dvt_partition_key"],
        output_columns=["id"],
        partition_key_name="category",
        partition_key_kind=ValueKind.STRING,
        strategy=PartitionStrategy.HASH,
        segments=[
            ReadSegment(
                label="h0",
                predicate_sql="1=1",
                order_by_sql="ORDER BY id ASC",
                division=SegmentDivision(start=0, end=1, include_end=False),
                strategy=PartitionStrategy.HASH,
            )
        ],
        divisions=(0, 1),
        max_rows_per_partition=100,
        index_column_name="__dvt_partition_bucket",
    )

    df = executor.load_partition(plan, plan.segments[0])

    assert list(df.columns) == ["id"]
    assert not any(str(column).lower().startswith("__dvt_") for column in df.columns)


def test_dtype_for_kind_maps_string_to_string_dtype() -> None:
    assert SQLReadExecutor._dtype_for_kind(ValueKind.STRING) == "string"


def test_dtype_for_kind_maps_uuid_to_string_dtype() -> None:
    assert SQLReadExecutor._dtype_for_kind(ValueKind.UUID) == "string"


def test_dtype_for_kind_maps_json_to_object_dtype() -> None:
    assert SQLReadExecutor._dtype_for_kind(ValueKind.JSON) == "object"


def test_dtype_for_kind_uses_plan_datetime_precision() -> None:
    plan = ReadV3Plan(
        mode=ReadMode.TABLE,
        dialect="sqlite",
        cte_prefix_sql=None,
        relation_sql="FROM users",
        select_exprs=["deadline_at"],
        output_columns=["deadline_at"],
        partition_key_name="deadline_at",
        partition_key_kind=ValueKind.DATETIME,
        strategy=PartitionStrategy.RANGE,
        segments=[],
        divisions=(),
        max_rows_per_partition=100,
        datetime_precision=ReadV3DateTimePrecision.SECONDS,
    )

    assert SQLReadExecutor._dtype_for_kind(ValueKind.DATETIME, plan=plan) == "datetime64[s]"


def test_normalize_datetime_series_supports_out_of_bounds_microseconds() -> None:
    result = SQLReadExecutor._normalize_datetime_series(
        pd.Series(["3999-08-31"]),
        "datetime64[us]",
    )

    assert str(result.dtype) == "datetime64[us]"
    assert str(result.iloc[0]) == "3999-08-31 00:00:00"


def test_normalize_datetime_series_keeps_nanoseconds_strict() -> None:
    with pytest.raises(pd.errors.OutOfBoundsDatetime):
        SQLReadExecutor._normalize_datetime_series(
            pd.Series(["3999-08-31"]),
            "datetime64[ns]",
        )


def test_dtype_for_kind_rejects_unknown_kind() -> None:
    with pytest.raises(ReadV3ExecutionError, match="does not support output column kind"):
        SQLReadExecutor._dtype_for_kind(ValueKind.UNKNOWN)


def test_dtype_for_column_error_includes_source_column_kind_and_type() -> None:
    plan = ReadV3Plan(
        mode=ReadMode.TABLE,
        dialect="sqlite",
        cte_prefix_sql=None,
        relation_sql="FROM users",
        select_exprs=["id", "payload"],
        output_columns=["id", "payload"],
        partition_key_name="id",
        partition_key_kind=ValueKind.NUMERIC,
        strategy=PartitionStrategy.RANGE,
        segments=[
            ReadSegment(
                label="p0",
                predicate_sql="id >= 1 AND id <= 1",
                order_by_sql="ORDER BY id ASC",
                division=SegmentDivision(start=1, end=1, include_end=True),
                strategy=PartitionStrategy.RANGE,
            )
        ],
        divisions=(1, 1),
        max_rows_per_partition=100,
        output_column_kinds={
            "id": ValueKind.NUMERIC,
            "payload": ValueKind.UNKNOWN,
        },
        output_column_type_repr={
            "id": "INTEGER",
            "payload": "BLOB",
        },
        source_table_name="read_v3_payload_test",
    )

    with pytest.raises(
        ReadV3ExecutionError,
        match="kind='unknown'.*column='payload'.*type='BLOB'.*source='read_v3_payload_test'",
    ):
        SQLReadExecutor._dtype_for_column(plan, "payload")


def test_load_partition_casts_string_columns_to_string_dtype(monkeypatch) -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    executor = SQLReadExecutor(engine)

    payload = pd.DataFrame(
        {
            "id": pd.Series([1, 2], dtype="int64"),
            "category": pd.Series(["alpha", "beta"], dtype="object"),
        }
    )
    monkeypatch.setattr(executor, "_read_sql_bounded", lambda *_args, **_kwargs: payload.copy())

    plan = ReadV3Plan(
        mode=ReadMode.TABLE,
        dialect="sqlite",
        cte_prefix_sql=None,
        relation_sql="FROM users",
        select_exprs=["id", "category"],
        output_columns=["id", "category"],
        partition_key_name="id",
        partition_key_kind=ValueKind.NUMERIC,
        strategy=PartitionStrategy.RANGE,
        segments=[
            ReadSegment(
                label="p0",
                predicate_sql="id >= 1 AND id <= 2",
                order_by_sql="ORDER BY id ASC",
                division=SegmentDivision(start=1, end=2, include_end=True),
                strategy=PartitionStrategy.RANGE,
            )
        ],
        divisions=(1, 2),
        max_rows_per_partition=100,
        output_column_kinds={
            "id": ValueKind.NUMERIC,
            "category": ValueKind.STRING,
        },
    )

    df = executor.load_partition(plan, plan.segments[0])

    assert df["category"].dtype.name == "string"
    assert df["category"].tolist() == ["alpha", "beta"]


def test_load_partition_preserves_json_columns_as_object_dtype(monkeypatch) -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    executor = SQLReadExecutor(engine)

    payload = pd.DataFrame(
        {
            "id": pd.Series([1, 2], dtype="int64"),
            "payload": pd.Series([{"alpha": 1}, ["beta"]], dtype="object"),
        }
    )
    monkeypatch.setattr(executor, "_read_sql_bounded", lambda *_args, **_kwargs: payload.copy())

    plan = ReadV3Plan(
        mode=ReadMode.TABLE,
        dialect="sqlite",
        cte_prefix_sql=None,
        relation_sql="FROM users",
        select_exprs=["id", "payload"],
        output_columns=["id", "payload"],
        partition_key_name="id",
        partition_key_kind=ValueKind.NUMERIC,
        strategy=PartitionStrategy.RANGE,
        segments=[
            ReadSegment(
                label="p0",
                predicate_sql="id >= 1 AND id <= 2",
                order_by_sql="ORDER BY id ASC",
                division=SegmentDivision(start=1, end=2, include_end=True),
                strategy=PartitionStrategy.RANGE,
            )
        ],
        divisions=(1, 2),
        max_rows_per_partition=100,
        output_column_kinds={
            "id": ValueKind.NUMERIC,
            "payload": ValueKind.JSON,
        },
    )

    df = executor.load_partition(plan, plan.segments[0])

    assert df["payload"].dtype == object
    assert df["payload"].tolist() == [{"alpha": 1}, ["beta"]]


def test_load_partition_casts_mssql_binary_columns_to_hex_string_dtype(monkeypatch) -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    executor = SQLReadExecutor(engine)

    payload = pd.DataFrame(
        {
            "id": pd.Series([1, 2], dtype="int64"),
            "bin_col": pd.Series([b"\x00\xff", memoryview(b"ab")], dtype="object"),
        }
    )
    monkeypatch.setattr(executor, "_read_sql_bounded", lambda *_args, **_kwargs: payload.copy())

    plan = ReadV3Plan(
        mode=ReadMode.TABLE,
        dialect="mssql",
        cte_prefix_sql=None,
        relation_sql="FROM users",
        select_exprs=["id", "bin_col"],
        output_columns=["id", "bin_col"],
        partition_key_name="id",
        partition_key_kind=ValueKind.NUMERIC,
        strategy=PartitionStrategy.RANGE,
        segments=[
            ReadSegment(
                label="p0",
                predicate_sql="id >= 1 AND id <= 2",
                order_by_sql="ORDER BY id ASC",
                division=SegmentDivision(start=1, end=2, include_end=True),
                strategy=PartitionStrategy.RANGE,
            )
        ],
        divisions=(1, 2),
        max_rows_per_partition=100,
        output_column_kinds={
            "id": ValueKind.NUMERIC,
            "bin_col": ValueKind.STRING,
        },
        output_column_type_repr={
            "id": "INT",
            "bin_col": "VARBINARY(2)",
        },
    )

    df = executor.load_partition(plan, plan.segments[0])

    assert df["bin_col"].dtype.name == "string"
    assert df["bin_col"].tolist() == ["00FF", "6162"]


def test_build_meta_uses_output_select_expressions_for_mssql_casts(monkeypatch) -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    executor = SQLReadExecutor(engine)
    captured_sql: list[str] = []

    def _fake_read_sql_query(sql, *_args, **_kwargs):
        captured_sql.append(str(sql))
        return pd.DataFrame(
            {
                "guid_col": pd.Series(["12345678-1234-5678-1234-567812345678"], dtype="object"),
                "bin_col": pd.Series(["00FF"], dtype="object"),
            }
        )

    monkeypatch.setattr(executor.sql_runner, "query_df", _fake_read_sql_query)

    plan = ReadV3Plan(
        mode=ReadMode.TABLE,
        dialect="mssql",
        cte_prefix_sql=None,
        relation_sql="FROM [dbo].[events]",
        select_exprs=["guid_col", "bin_col"],
        output_columns=["guid_col", "bin_col"],
        partition_key_name="guid_col",
        partition_key_kind=ValueKind.UUID,
        strategy=PartitionStrategy.HASH,
        segments=[
            ReadSegment(
                label="h0",
                predicate_sql="1=1",
                order_by_sql="ORDER BY [guid_col] ASC",
                division=SegmentDivision(start=0, end=1, include_end=False),
                strategy=PartitionStrategy.HASH,
            )
        ],
        divisions=(0, 1),
        max_rows_per_partition=100,
        output_column_kinds={
            "guid_col": ValueKind.UUID,
            "bin_col": ValueKind.STRING,
        },
        output_column_type_repr={
            "guid_col": "UNIQUEIDENTIFIER",
            "bin_col": "VARBINARY(2)",
        },
        output_column_select_exprs={
            "guid_col": "CAST([guid_col] AS NVARCHAR(MAX)) AS [guid_col]",
            "bin_col": "CONVERT(VARCHAR(MAX), [bin_col], 2) AS [bin_col]",
        },
        output_column_sql_names={
            "guid_col": "guid_col",
            "bin_col": "bin_col",
        },
        partition_key_sql_name="guid_col",
        index_column_name="__dvt_partition_bucket",
    )

    meta = executor.build_meta(plan)

    assert meta["guid_col"].dtype.name == "string"
    assert meta["bin_col"].dtype.name == "string"
    assert "CAST([guid_col] AS NVARCHAR(MAX)) AS [guid_col]" in captured_sql[0]
    assert "CONVERT(VARCHAR(MAX), [bin_col], 2) AS [bin_col]" in captured_sql[0]


def test_dtype_for_index_skips_string_dtype_for_raw_mssql_partition_helper() -> None:
    plan = ReadV3Plan(
        mode=ReadMode.TABLE,
        dialect="mssql",
        cte_prefix_sql=None,
        relation_sql="FROM [dbo].[events]",
        select_exprs=["CAST([guid_col] AS NVARCHAR(MAX)) AS [guid_col]", "[guid_col] AS [__dvt_partition_key]"],
        output_columns=["guid_col"],
        partition_key_name="guid_col",
        partition_key_kind=ValueKind.UUID,
        strategy=PartitionStrategy.RANGE,
        segments=[],
        divisions=(),
        max_rows_per_partition=100,
        partition_key_type_repr="UNIQUEIDENTIFIER",
        index_column_name="__dvt_partition_key",
    )

    assert SQLReadExecutor._dtype_for_index(plan) is None


def _probe_concurrent_queries(monkeypatch, executor, *, parties: int) -> dict[str, int]:
    """Count partition queries inside the runner; the barrier needs `parties` of them at once."""
    lock = threading.Lock()
    barrier = threading.Barrier(parties, timeout=10)
    state = {"active": 0, "peak": 0}
    real_query_df = executor.sql_runner.query_df

    def _probe(sql: str) -> pd.DataFrame:
        with lock:
            state["active"] += 1
            state["peak"] = max(state["peak"], state["active"])
        try:
            barrier.wait()
            return real_query_df(sql)
        finally:
            with lock:
                state["active"] -= 1

    monkeypatch.setattr(executor.sql_runner, "query_df", _probe)
    return state


def _eight_segment_plan(tmp_path) -> tuple[sa.Engine, ReadV3Plan]:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'concurrency.sqlite'}")
    _seed(engine, rows=32)
    plan = resolve_planner(mode="table").build_plan(
        engine=engine,
        table_name="read_v3_exec_test",
        columns=["id", "category"],
        partition_col="id",
        npartitions=8,
        max_rows_per_partition=100,
        **STRICT_PARTITIONING_KWARGS,
    )
    assert len(plan.segments) == 8
    return engine, plan


@pytest.mark.parametrize("limit", [1, 2, 4])
def test_load_partition_limits_concurrent_queries_regardless_of_thread_pool(
    monkeypatch, tmp_path, limit
) -> None:
    engine, plan = _eight_segment_plan(tmp_path)
    executor = resolve_executor(engine, max_concurrent_queries=limit)
    meta = executor.build_meta(plan)
    state = _probe_concurrent_queries(monkeypatch, executor, parties=limit)

    df = frame_from_executor(executor, plan, meta=meta).compute(
        scheduler="threads", num_workers=8
    )

    assert len(df) == 32
    assert state["peak"] == limit


def test_load_partition_without_limit_uses_the_whole_thread_pool(monkeypatch, tmp_path) -> None:
    engine, plan = _eight_segment_plan(tmp_path)
    executor = resolve_executor(engine)
    meta = executor.build_meta(plan)
    state = _probe_concurrent_queries(monkeypatch, executor, parties=8)

    df = frame_from_executor(executor, plan, meta=meta).compute(
        scheduler="threads", num_workers=8
    )

    assert len(df) == 32
    assert state["peak"] == 8


def test_query_limit_is_a_no_op_for_the_sync_scheduler(tmp_path) -> None:
    engine, plan = _eight_segment_plan(tmp_path)
    executor = resolve_executor(engine, max_concurrent_queries=1)

    df = frame_from_executor(executor, plan).compute(scheduler="sync")

    assert sorted(df["id"].tolist()) == list(range(1, 33))


def test_executor_rejects_non_positive_query_limit() -> None:
    with pytest.raises(ReadV3ConfigError, match="max_concurrent_queries"):
        SQLReadExecutor(sa.create_engine("sqlite://"), max_concurrent_queries=0)


def _decimal_range_plan(
    *,
    output_columns: list[str],
    index_column_name: str,
    type_repr: str = "Decimal(18, 4)",
    divisions: tuple = (Decimal("190.6666"), Decimal("381.3333"), Decimal("572.0000")),
) -> ReadV3Plan:
    segments = [
        ReadSegment(
            label=f"range_{idx}",
            predicate_sql="1=1",
            order_by_sql="ORDER BY k ASC",
            division=SegmentDivision(
                start=divisions[idx],
                end=divisions[idx + 1],
                include_end=idx == len(divisions) - 2,
            ),
            strategy=PartitionStrategy.RANGE,
        )
        for idx in range(len(divisions) - 1)
    ]
    return ReadV3Plan(
        mode=ReadMode.TABLE,
        dialect="clickhouse",
        cte_prefix_sql=None,
        relation_sql="FROM t",
        select_exprs=["id", "k"],
        output_columns=output_columns,
        partition_key_name="k",
        partition_key_kind=ValueKind.NUMERIC,
        strategy=PartitionStrategy.RANGE,
        segments=segments,
        divisions=divisions,
        max_rows_per_partition=100,
        partition_key_type_repr=type_repr,
        index_column_name=index_column_name,
        output_column_kinds={"id": ValueKind.NUMERIC, "k": ValueKind.NUMERIC},
        output_column_type_repr={"id": "Int64", "k": type_repr},
    )


@pytest.mark.parametrize(
    ("output_columns", "index_column_name", "key_column"),
    [
        (["id", "k"], "k", "k"),
        (["id"], "__dvt_partition_key", "__dvt_partition_key"),
    ],
    ids=["key_in_output", "helper_key"],
)
def test_decimal_range_key_index_keeps_exact_values(
    monkeypatch, output_columns, index_column_name, key_column
) -> None:
    executor = SQLReadExecutor(sa.create_engine("sqlite:///:memory:"))
    plan = _decimal_range_plan(output_columns=output_columns, index_column_name=index_column_name)
    # float(Decimal("190.6666")) == 190.66659999999999 < Decimal("190.6666"): a float64 index
    # would put the segment's first row below its own start.
    keys = [Decimal("190.6666"), Decimal("200.0001"), Decimal("381.3332")]
    payload = pd.DataFrame({"id": [1, 2, 3], key_column: pd.Series(keys, dtype="object")})
    monkeypatch.setattr(executor, "_read_sql_bounded", lambda *_args, **_kwargs: payload.copy())

    df = executor.load_partition(plan, plan.segments[0])

    assert df.index.tolist() == keys
    assert all(type(value) is Decimal for value in df.index)
    assert list(df.columns) == output_columns
    if "k" in output_columns:
        assert str(df["k"].dtype) == "float64"
        assert df["k"].tolist() == [float(value) for value in keys]
    assert executor._dtype_for_index(plan) is None


def test_decimal_range_key_bounds_compare_exactly() -> None:
    plan = _decimal_range_plan(output_columns=["id", "k"], index_column_name="k")
    segment = plan.segments[0]

    def _frame(*keys: Decimal) -> pd.DataFrame:
        return pd.DataFrame({"id": range(len(keys))}, index=pd.Index(list(keys), dtype=object))

    SQLReadExecutor._validate_index_bounds(_frame(Decimal("190.6666"), Decimal("381.3332")), segment)
    with pytest.raises(ReadV3ExecutionError, match="upper bound violation"):
        SQLReadExecutor._validate_index_bounds(_frame(Decimal("381.3333")), segment)
    with pytest.raises(ReadV3ExecutionError, match="lower bound violation"):
        SQLReadExecutor._validate_index_bounds(_frame(Decimal("190.6665")), segment)
    # The float64 key cast that used to be the index fails the segment's own first row.
    with pytest.raises(ReadV3ExecutionError, match="lower bound violation"):
        SQLReadExecutor._validate_index_bounds(
            pd.DataFrame({"id": [0]}, index=pd.Index([float(Decimal("190.6666"))])), segment
        )


@pytest.mark.parametrize(
    ("type_repr", "divisions", "expected"),
    [
        # Integer decimals keep the Int64 index; float keys keep the float64 index.
        ("Decimal(18, 0)", (Decimal("1"), Decimal("5"), Decimal("9")), "Int64"),
        ("Float64", (0.5, 1.25, 2.0), "float64"),
        ("Int64", (1, 5, 9), "Int64"),
    ],
)
def test_index_dtype_unchanged_for_non_fractional_decimal_keys(type_repr, divisions, expected):
    plan = _decimal_range_plan(
        output_columns=["id", "k"], index_column_name="k", type_repr=type_repr, divisions=divisions
    )

    assert SQLReadExecutor._uses_exact_decimal_index(plan) is False
    assert SQLReadExecutor._dtype_for_index(plan) == expected


def _hints_plan(kinds: dict[str, tuple[ValueKind, str]]) -> ReadV3Plan:
    columns = list(kinds)
    return ReadV3Plan(
        mode=ReadMode.QUERY,
        dialect="postgresql",
        cte_prefix_sql=None,
        relation_sql="FROM t",
        select_exprs=columns,
        output_columns=columns,
        partition_key_name=columns[0],
        partition_key_kind=ValueKind.NUMERIC,
        strategy=PartitionStrategy.RANGE,
        segments=[],
        divisions=(0, 1),
        max_rows_per_partition=10,
        output_column_kinds={column: kind for column, (kind, _repr) in kinds.items()},
        output_column_type_repr={column: type_repr for column, (_kind, type_repr) in kinds.items()},
    )


def test_output_type_hints_skip_columns_already_at_the_target_dtype(monkeypatch) -> None:
    def _fail(*_args, **_kwargs):
        raise AssertionError("a column at its target dtype was cast again")

    for name in ("_normalize_datetime_series", "_normalize_boolean_series", "_normalize_string_series"):
        monkeypatch.setattr(SQLReadExecutor, name, _fail)
    plan = _hints_plan(
        {
            "i": (ValueKind.NUMERIC, "int8"),
            "f": (ValueKind.NUMERIC, "float8"),
            "b": (ValueKind.BOOL, "bool"),
            "s": (ValueKind.STRING, "text"),
            "d": (ValueKind.DATETIME, "timestamp"),
            "j": (ValueKind.JSON, "jsonb"),
        }
    )
    df = pd.DataFrame(
        {
            "i": pd.array([1, None], dtype="Int64"),
            "f": [0.5, float("nan")],
            "b": pd.array([True, None], dtype="boolean"),
            "s": pd.array(["a", None], dtype=pd.api.types.pandas_dtype("string")),
            "d": pd.Series(pd.to_datetime(["2024-01-01", None])).astype("datetime64[us]"),
            "j": pd.Series([{"a": 1}, None], dtype=object),
        }
    )
    expected = df.copy()

    result = SQLReadExecutor._apply_output_type_hints(df, plan, stage="test")

    pd.testing.assert_frame_equal(result, expected)
    assert result["j"].tolist() == [{"a": 1}, None]


def test_output_type_hints_still_cast_the_inferred_str_dtype_to_string() -> None:
    plan = _hints_plan({"s": (ValueKind.STRING, "text")})
    df = pd.DataFrame([("a",), (None,)], columns=["s"])
    assert df["s"].dtype == "string"  # the alias matches the NaN-backed str dtype ...
    assert df["s"].dtype != pd.api.types.pandas_dtype("string")  # ... the dtype object does not

    result = SQLReadExecutor._apply_output_type_hints(df, plan, stage="test")

    assert result["s"].dtype == pd.api.types.pandas_dtype("string")
    assert result["s"].tolist() == ["a", pd.NA]


def test_output_type_hints_cast_duplicate_named_columns() -> None:
    plan = _hints_plan({"x": (ValueKind.NUMERIC, "int8")})
    df = pd.DataFrame([[1, 2]], columns=["x", "x"])

    result = SQLReadExecutor._apply_output_type_hints(df, plan, stage="test")

    assert [str(dtype) for dtype in result.dtypes] == ["Int64", "Int64"]
