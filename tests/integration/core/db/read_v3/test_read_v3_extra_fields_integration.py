from __future__ import annotations

import contextlib
from datetime import datetime, timedelta
from importlib.util import find_spec
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError
from tests.integration.src.nodes.extract.read_db_v3_matrix_helpers import ALL_SQL_DB_ENGINE_FIXTURES

from core.db.read_v3.dask import frame_from_executor
from core.db.read_v3.errors import ReadV3PlanningError
from core.db.read_v3.resolver import resolve_executor, resolve_planner

import config

pytestmark = pytest.mark.docker_required

STRICT_PARTITIONING_KWARGS = {
    "min_rows_per_partition": config.DASK_PARTITIONING.MIN_ROWS_PER_PART,
    "target_partition_mem_mb": config.DASK_PARTITIONING.TARGET_PARTITION_MEM_MB,
    "partitioning_overhead_coef": config.DASK_PARTITIONING.OVERHEAD_COEF,
    "max_partitions": config.DASK_PARTITIONING.MAX_PARTITIONS,
}


def _dialect_family(engine: sa.Engine) -> str:
    name = (engine.dialect.name or "").lower()
    if "clickhouse" in name:
        return "clickhouse"
    if "postgres" in name:
        return "postgres"
    if "mysql" in name:
        return "mysql"
    if "mssql" in name or "sqlserver" in name:
        return "mssql"
    if "oracle" in name:
        return "oracle"
    return name


def _table_name(prefix: str, engine: sa.Engine) -> str:
    dialect_code = {
        "postgres": "pg",
        "mysql": "my",
        "mssql": "ms",
        "oracle": "or",
        "clickhouse": "ch",
    }.get(_dialect_family(engine), "db")
    suffix = uuid4().hex[:8]
    table_name = f"rv3_{prefix}_{dialect_code}_{suffix}"[:30]
    if _dialect_family(engine) == "oracle":
        return table_name.upper()
    return table_name


def _skip_if_mssql_driver_missing(engine_fixture: str) -> None:
    if engine_fixture == "mssql_test_engine" and find_spec("pyodbc") is None:
        pytest.skip("pyodbc is not installed; MSSQL integration tests are skipped")


def _build_rows(nrows: int = 8) -> list[dict[str, object]]:
    base_ts = datetime(2026, 1, 1, 0, 0, 0)
    rows: list[dict[str, object]] = []
    categories = ["A", "B", "C"]
    for idx in range(1, nrows + 1):
        rows.append(
            {
                "id": idx,
                "category": categories[idx % len(categories)],
                "created_at": base_ts + timedelta(minutes=idx),
            }
        )
    return rows


def _drop_table(engine: sa.Engine, table_name: str) -> None:
    family = _dialect_family(engine)
    with engine.begin() as conn:
        if family == "mssql":
            conn.execute(
                text(f"IF OBJECT_ID(N'{table_name}', N'U') IS NOT NULL DROP TABLE {table_name}")
            )
            return
        if family == "oracle":
            with contextlib.suppress(DatabaseError):
                conn.execute(text(f"DROP TABLE {table_name}"))
            return
        conn.execute(text(f"DROP TABLE IF EXISTS {table_name}"))


def _create_table(engine: sa.Engine, table_name: str) -> None:
    family = _dialect_family(engine)
    with engine.begin() as conn:
        if family == "postgres":
            conn.execute(
                text(
                    f"""
                    CREATE TABLE {table_name} (
                        id INTEGER PRIMARY KEY,
                        category VARCHAR(16),
                        created_at TIMESTAMP
                    )
                    """
                )
            )
            return
        if family == "mysql":
            conn.execute(
                text(
                    f"""
                    CREATE TABLE {table_name} (
                        id INT PRIMARY KEY,
                        category VARCHAR(16),
                        created_at DATETIME
                    )
                    """
                )
            )
            return
        if family == "mssql":
            conn.execute(
                text(
                    f"""
                    CREATE TABLE {table_name} (
                        id INT PRIMARY KEY,
                        category NVARCHAR(16),
                        created_at DATETIME2
                    )
                    """
                )
            )
            return
        if family == "oracle":
            conn.execute(
                text(
                    f"""
                    CREATE TABLE {table_name} (
                        id NUMBER(10) PRIMARY KEY,
                        category VARCHAR2(16),
                        created_at TIMESTAMP
                    )
                    """
                )
            )
            return
        if family == "clickhouse":
            conn.execute(
                text(
                    f"""
                    CREATE TABLE {table_name} (
                        id Int32,
                        category String,
                        created_at DateTime
                    ) ENGINE = Memory
                    """
                )
            )
            return
        raise ValueError(f"Unsupported dialect family: {family}")


def _insert_rows(engine: sa.Engine, table_name: str, rows: list[dict[str, object]]) -> None:
    family = _dialect_family(engine)
    with engine.begin() as conn:
        if family == "clickhouse":
            values_sql = ", ".join(
                "("
                + ", ".join(
                    [
                        str(int(row["id"])),
                        "'" + str(row["category"]).replace("'", "''") + "'",
                        "toDateTime('" + row["created_at"].strftime("%Y-%m-%d %H:%M:%S") + "')",
                    ]
                )
                + ")"
                for row in rows
            )
            conn.execute(
                text(f"INSERT INTO {table_name} (id, category, created_at) VALUES {values_sql}")
            )
            return

        conn.execute(
            text(
                f"""
                INSERT INTO {table_name} (id, category, created_at)
                VALUES (:id, :category, :created_at)
                """
            ),
            rows,
        )


def _seed_table(engine: sa.Engine, table_name: str, rows: list[dict[str, object]]) -> None:
    _create_table(engine, table_name)
    _insert_rows(engine, table_name, rows)


def _normalized_column_name(name: object) -> str:
    return str(name).strip().strip('[]`"').lower()


def _assert_output_has_only_expected_columns(
    columns: list[object],
    *,
    expected_columns: list[str],
) -> None:
    normalized_actual = [_normalized_column_name(column) for column in columns]
    normalized_expected = [_normalized_column_name(column) for column in expected_columns]

    assert len(normalized_actual) == len(normalized_expected)
    assert set(normalized_actual) == set(normalized_expected)
    assert all(not column.startswith("__dvt_") for column in normalized_actual)


@pytest.mark.parametrize("engine_fixture", ALL_SQL_DB_ENGINE_FIXTURES)
def test_read_v3_table_mode_rejects_extra_columns_across_databases(
    engine_fixture: str,
    request: pytest.FixtureRequest,
) -> None:
    _skip_if_mssql_driver_missing(engine_fixture)
    engine: sa.Engine = request.getfixturevalue(engine_fixture)
    table_name = _table_name("tbl_extra", engine)
    rows = _build_rows()
    _seed_table(engine, table_name, rows)

    try:
        planner = resolve_planner(mode="table")
        with pytest.raises(ReadV3PlanningError, match="was not found in table columns"):
            planner.build_plan(
                engine=engine,
                table_name=table_name,
                columns=["id", "category", "missing_column"],
                partition_col="id",
                npartitions=3,
                **STRICT_PARTITIONING_KWARGS,
            )
    finally:
        _drop_table(engine, table_name)


@pytest.mark.parametrize("engine_fixture", ALL_SQL_DB_ENGINE_FIXTURES)
def test_read_v3_query_mode_rejects_extra_columns_across_databases(
    engine_fixture: str,
    request: pytest.FixtureRequest,
) -> None:
    _skip_if_mssql_driver_missing(engine_fixture)
    engine: sa.Engine = request.getfixturevalue(engine_fixture)
    table_name = _table_name("qry_extra", engine)
    rows = _build_rows()
    _seed_table(engine, table_name, rows)

    try:
        planner = resolve_planner(mode="query")
        with pytest.raises(ReadV3PlanningError, match="was not found in query result columns"):
            planner.build_plan(
                engine=engine,
                query=f"SELECT id, category FROM {table_name}",
                columns=["id", "category", "missing_column"],
                partition_col="id",
                npartitions=3,
                **STRICT_PARTITIONING_KWARGS,
            )
    finally:
        _drop_table(engine, table_name)


@pytest.mark.parametrize("engine_fixture", ALL_SQL_DB_ENGINE_FIXTURES)
def test_read_v3_table_mode_output_contains_only_requested_columns_across_databases(
    engine_fixture: str,
    request: pytest.FixtureRequest,
) -> None:
    _skip_if_mssql_driver_missing(engine_fixture)
    engine: sa.Engine = request.getfixturevalue(engine_fixture)
    table_name = _table_name("tbl_cols", engine)
    rows = _build_rows()
    _seed_table(engine, table_name, rows)

    try:
        planner = resolve_planner(mode="table")
        plan = planner.build_plan(
            engine=engine,
            table_name=table_name,
            columns=["category"],
            partition_col="id",
            npartitions=3,
            **STRICT_PARTITIONING_KWARGS,
        )
        executor = resolve_executor(engine)
        ddf = frame_from_executor(executor, plan)
        result = ddf.compute()

        _assert_output_has_only_expected_columns(
            list(result.columns),
            expected_columns=["category"],
        )
    finally:
        _drop_table(engine, table_name)


@pytest.mark.parametrize("engine_fixture", ALL_SQL_DB_ENGINE_FIXTURES)
def test_read_v3_table_mode_hash_output_contains_only_requested_columns_across_databases(
    engine_fixture: str,
    request: pytest.FixtureRequest,
) -> None:
    _skip_if_mssql_driver_missing(engine_fixture)
    engine: sa.Engine = request.getfixturevalue(engine_fixture)
    table_name = _table_name("tbl_hash", engine)
    rows = _build_rows()
    _seed_table(engine, table_name, rows)

    try:
        planner = resolve_planner(mode="table")
        plan = planner.build_plan(
            engine=engine,
            table_name=table_name,
            columns=["id"],
            partition_col="category",
            partition_grouping={"mode": "hash", "buckets": 4},
            npartitions=2,
            **STRICT_PARTITIONING_KWARGS,
        )
        executor = resolve_executor(engine)
        ddf = frame_from_executor(executor, plan)
        result = ddf.compute()

        _assert_output_has_only_expected_columns(
            list(result.columns),
            expected_columns=["id"],
        )
    finally:
        _drop_table(engine, table_name)


@pytest.mark.parametrize("engine_fixture", ALL_SQL_DB_ENGINE_FIXTURES)
def test_read_v3_query_mode_output_contains_only_requested_columns_across_databases(
    engine_fixture: str,
    request: pytest.FixtureRequest,
) -> None:
    _skip_if_mssql_driver_missing(engine_fixture)
    engine: sa.Engine = request.getfixturevalue(engine_fixture)
    table_name = _table_name("qry_cols", engine)
    rows = _build_rows()
    _seed_table(engine, table_name, rows)

    try:
        planner = resolve_planner(mode="query")
        plan = planner.build_plan(
            engine=engine,
            query=f"SELECT id, category, created_at FROM {table_name}",
            columns=["category"],
            partition_col="id",
            npartitions=3,
            **STRICT_PARTITIONING_KWARGS,
        )
        executor = resolve_executor(engine)
        ddf = frame_from_executor(executor, plan)
        result = ddf.compute()

        _assert_output_has_only_expected_columns(
            list(result.columns),
            expected_columns=["category"],
        )
    finally:
        _drop_table(engine, table_name)


@pytest.mark.parametrize("engine_fixture", ALL_SQL_DB_ENGINE_FIXTURES)
def test_read_v3_query_mode_grouped_output_contains_only_requested_columns_across_databases(
    engine_fixture: str,
    request: pytest.FixtureRequest,
) -> None:
    _skip_if_mssql_driver_missing(engine_fixture)
    engine: sa.Engine = request.getfixturevalue(engine_fixture)
    table_name = _table_name("qry_grp", engine)
    rows = _build_rows()
    _seed_table(engine, table_name, rows)

    try:
        planner = resolve_planner(mode="query")
        plan = planner.build_plan(
            engine=engine,
            query=f"SELECT id, category FROM {table_name}",
            columns=["id"],
            partition_col="category",
            partition_grouping={"mode": "explicit_values", "values": ["A", "B"], "other": True},
            npartitions=3,
            **STRICT_PARTITIONING_KWARGS,
        )
        executor = resolve_executor(engine)
        ddf = frame_from_executor(executor, plan)
        result = ddf.compute()

        _assert_output_has_only_expected_columns(
            list(result.columns),
            expected_columns=["id"],
        )
    finally:
        _drop_table(engine, table_name)
