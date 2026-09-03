from __future__ import annotations

from datetime import datetime, timedelta
from importlib.util import find_spec
from uuid import uuid4

import pandas as pd
import pytest
import sqlalchemy as sa
from sqlalchemy import text

from core.db.read_v3.dask import frame_from_executor
from core.db.read_v3.resolver import resolve_executor, resolve_planner

import config

pytestmark = pytest.mark.docker_required


STRICT_PARTITIONING_KWARGS = {
    "min_rows_per_partition": config.DASK_PARTITIONING.MIN_ROWS_PER_PART,
    "target_partition_mem_mb": config.DASK_PARTITIONING.TARGET_PARTITION_MEM_MB,
    "partitioning_overhead_coef": config.DASK_PARTITIONING.OVERHEAD_COEF,
    "max_partitions": config.DASK_PARTITIONING.MAX_PARTITIONS,
}


def _skip_if_mssql_driver_missing() -> None:
    if find_spec("pyodbc") is None:
        pytest.skip("pyodbc is not installed; MSSQL integration tests are skipped")


def _table_name(prefix: str) -> str:
    return f"rv3_{prefix}_{uuid4().hex[:8]}"


def _drop_table(engine: sa.Engine, table_name: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                f"IF OBJECT_ID(N'dbo.{table_name}', N'U') IS NOT NULL "
                f"DROP TABLE [dbo].[{table_name}]"
            )
        )


def _seed(engine: sa.Engine, table_name: str, rows: int = 120) -> list[dict[str, object]]:
    payload: list[dict[str, object]] = []
    base_ts = datetime(2026, 2, 20, 7, 0, 0)
    for idx in range(rows):
        payload.append(
            {
                "id": idx + 1,
                "category": ["alpha", "beta", "omega"][idx % 3],
                "created_at": base_ts + timedelta(minutes=idx),
                "value": float(idx) * 1.5,
            }
        )

    with engine.begin() as conn:
        conn.execute(
            text(
                f"""
                CREATE TABLE [dbo].[{table_name}] (
                    id INT PRIMARY KEY,
                    category NVARCHAR(32) NULL,
                    created_at DATETIME NOT NULL,
                    value FLOAT NULL
                )
                """
            )
        )
        conn.execute(
            text(
                f"""
                INSERT INTO [dbo].[{table_name}] (id, category, created_at, value)
                VALUES (:id, :category, :created_at, :value)
                """
            ),
            payload,
        )
    return payload


def test_read_v3_table_mode_mssql_datetime_grouping_granularity(
    request: pytest.FixtureRequest,
) -> None:
    _skip_if_mssql_driver_missing()
    engine: sa.Engine = request.getfixturevalue("mssql_test_engine")
    table_name = _table_name("tbl_dt")
    _drop_table(engine, table_name)

    try:
        rows = _seed(engine, table_name, rows=120)
        planner = resolve_planner(mode="table")
        plan = planner.build_plan(
            engine=engine,
            table_name=table_name,
            schema="dbo",
            columns=["id", "created_at", "value"],
            partition_col="created_at",
            partition_grouping={"mode": "granularity", "granularity": "hour"},
            npartitions=4,
            **STRICT_PARTITIONING_KWARGS,
        )
        executor = resolve_executor(engine)
        ddf = frame_from_executor(executor, plan)
        result = ddf.compute().sort_values("id").reset_index(drop=True)

        assert len(result) == len(rows)
        assert result["id"].tolist() == list(range(1, len(rows) + 1))
        assert any(
            "DATETIME2(6)" in segment.predicate_sql
            for segment in plan.segments
            if "created_at" in segment.predicate_sql
        )
    finally:
        _drop_table(engine, table_name)


def test_read_v3_query_mode_mssql_string_prefix_grouping(
    request: pytest.FixtureRequest,
) -> None:
    _skip_if_mssql_driver_missing()
    engine: sa.Engine = request.getfixturevalue("mssql_test_engine")
    table_name = _table_name("qry_str")
    _drop_table(engine, table_name)

    try:
        rows = _seed(engine, table_name, rows=30)

        planner = resolve_planner(mode="query")
        plan = planner.build_plan(
            engine=engine,
            query=f"SELECT TOP 12 id, category, value FROM [dbo].[{table_name}] ORDER BY id",
            partition_col="category",
            partition_grouping={"mode": "prefix", "length": 1},
            npartitions=4,
            **STRICT_PARTITIONING_KWARGS,
        )
        executor = resolve_executor(engine)
        ddf = frame_from_executor(executor, plan)
        result = ddf.compute().sort_values("id").reset_index(drop=True)

        assert len(result) == 12
        assert result["id"].tolist() == [row["id"] for row in rows[:12]]
        assert list(result.columns) == ["id", "category", "value"]
        assert any(
            "SUBSTRING([category], 1, 1)" in segment.predicate_sql
            for segment in plan.segments
        )
    finally:
        _drop_table(engine, table_name)


def test_read_v3_query_mode_mssql_datetime_grouping_ranges(
    request: pytest.FixtureRequest,
) -> None:
    _skip_if_mssql_driver_missing()
    engine: sa.Engine = request.getfixturevalue("mssql_test_engine")
    table_name = _table_name("qry_dt")
    _drop_table(engine, table_name)

    try:
        rows = _seed(engine, table_name, rows=120)
        base_ts = datetime(2026, 2, 20, 7, 0, 0)
        split_ts = base_ts + timedelta(hours=1)
        end_ts = base_ts + timedelta(minutes=119)

        planner = resolve_planner(mode="query")
        plan = planner.build_plan(
            engine=engine,
            query=f"SELECT id, created_at, value FROM [dbo].[{table_name}] ORDER BY created_at",
            partition_col="created_at",
            partition_grouping={
                "mode": "ranges",
                "ranges": [
                    [base_ts, split_ts, False],
                    [split_ts, end_ts, True],
                ],
            },
            npartitions=4,
            **STRICT_PARTITIONING_KWARGS,
        )
        executor = resolve_executor(engine)
        ddf = frame_from_executor(executor, plan)
        result = ddf.compute().sort_values("id").reset_index(drop=True)

        assert len(result) == len(rows)
        assert result["id"].tolist() == list(range(1, len(rows) + 1))
        assert pd.api.types.is_integer_dtype(ddf._meta["id"].dtype)
        assert pd.api.types.is_datetime64_any_dtype(ddf._meta["created_at"].dtype)
        assert pd.api.types.is_float_dtype(ddf._meta["value"].dtype)
        assert any(
            "DATETIME2(6)" in segment.predicate_sql
            for segment in plan.segments
            if "created_at" in segment.predicate_sql
        )
    finally:
        _drop_table(engine, table_name)


def test_read_v3_query_mode_mssql_supports_top_level_cte(
    request: pytest.FixtureRequest,
) -> None:
    _skip_if_mssql_driver_missing()
    engine: sa.Engine = request.getfixturevalue("mssql_test_engine")
    table_name = _table_name("qry_cte")
    _drop_table(engine, table_name)

    try:
        rows = _seed(engine, table_name, rows=30)

        planner = resolve_planner(mode="query")
        plan = planner.build_plan(
            engine=engine,
            query=(
                f"WITH seeded AS ("
                f"SELECT TOP 12 id, category, value FROM [dbo].[{table_name}] ORDER BY id"
                f") "
                f"SELECT id, category, value FROM seeded"
            ),
            partition_col="category",
            partition_grouping={"mode": "prefix", "length": 1},
            npartitions=4,
            **STRICT_PARTITIONING_KWARGS,
        )
        executor = resolve_executor(engine)
        ddf = frame_from_executor(executor, plan)
        result = ddf.compute().sort_values("id").reset_index(drop=True)

        assert len(result) == 12
        assert result["id"].tolist() == [row["id"] for row in rows[:12]]
        assert list(result.columns) == ["id", "category", "value"]
        assert plan.cte_prefix_sql.startswith("WITH seeded AS")
        assert "user_query AS (SELECT id AS id, category AS category, value AS value FROM seeded)" in (
            plan.cte_prefix_sql
        )
    finally:
        _drop_table(engine, table_name)


def test_read_v3_table_mode_mssql_supports_extended_system_types(
    request: pytest.FixtureRequest,
) -> None:
    _skip_if_mssql_driver_missing()
    engine: sa.Engine = request.getfixturevalue("mssql_test_engine")
    table_name = _table_name("system_types")
    _drop_table(engine, table_name)

    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    f"""
                    CREATE TABLE [dbo].[{table_name}] (
                        id INT PRIMARY KEY,
                        flag BIT NOT NULL,
                        amount MONEY NULL,
                        small_amount SMALLMONEY NULL,
                        clock TIME(6) NULL,
                        payload IMAGE NULL,
                        row_version ROWVERSION,
                        document XML NULL,
                        variant SQL_VARIANT NULL,
                        node HIERARCHYID NULL,
                        shape GEOMETRY NULL,
                        point GEOGRAPHY NULL
                    )
                    """
                )
            )
            conn.execute(
                text(
                    f"""
                    INSERT INTO [dbo].[{table_name}]
                        (
                            id, flag, amount, small_amount, clock, payload, document, variant,
                            node, shape, point
                        )
                    VALUES
                        (
                            1, 1, CAST(12.34 AS MONEY), CAST(5.67 AS SMALLMONEY),
                            CAST('07:08:09.123456' AS TIME(6)), 0x00AB,
                            N'<root id="1" />', CAST(N'hello' AS SQL_VARIANT),
                            hierarchyid::Parse('/1/'),
                            geometry::STGeomFromText('POINT (1 2)', 0),
                            geography::STGeomFromText('POINT (30 10)', 4326)
                        ),
                        (
                            2, 0, CAST(-5.5 AS MONEY), CAST(0 AS SMALLMONEY),
                            CAST('23:59:59' AS TIME(6)), 0xFF,
                            N'<root id="2" />', CAST(42 AS SQL_VARIANT),
                            hierarchyid::Parse('/2/'),
                            geometry::STGeomFromText('LINESTRING (0 0, 1 1)', 0),
                            geography::STGeomFromText('POINT (40 20)', 4326)
                        )
                    """
                )
            )

        selected_columns = [
            "id",
            "flag",
            "amount",
            "small_amount",
            "clock",
            "payload",
            "row_version",
            "document",
            "variant",
            "node",
            "shape",
            "point",
        ]
        plan = resolve_planner(mode="table").build_plan(
            engine=engine,
            table_name=table_name,
            schema="dbo",
            columns=selected_columns,
            partition_col="id",
            npartitions=2,
            **STRICT_PARTITIONING_KWARGS,
        )
        result = (
            frame_from_executor(resolve_executor(engine), plan)
            .compute()
            .reset_index(drop=True)
            .sort_values("id")
            .reset_index(drop=True)
        )

        assert result["flag"].tolist() == [True, False]
        assert result["amount"].tolist() == pytest.approx([12.34, -5.5])
        assert result["small_amount"].tolist() == pytest.approx([5.67, 0.0])
        assert result["clock"].tolist() == ["07:08:09.123456", "23:59:59.000000"]
        assert result["payload"].tolist() == ["00AB", "FF"]
        row_versions = result["row_version"].tolist()
        assert all(len(value) == 16 for value in row_versions), (
            repr(row_versions),
            plan.output_column_type_repr["row_version"],
            plan.output_column_select_exprs["row_version"],
        )
        assert result["document"].str.contains("<root").all()
        assert result["variant"].tolist() == ["hello", "42"]
        assert result["node"].tolist() == ["/1/", "/2/"]
        assert result["shape"].tolist() == ["POINT (1 2)", "LINESTRING (0 0, 1 1)"]
        assert result["point"].tolist() == ["POINT (30 10)", "POINT (40 20)"]
    finally:
        _drop_table(engine, table_name)
