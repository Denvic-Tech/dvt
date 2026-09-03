from __future__ import annotations

import pytest
import sqlalchemy as sa

from src.nodes.extract.read_query_from_db_v3 import ReadQueryFromDBV3
from tests.integration.src.nodes.extract.read_db_v3_matrix_helpers import (
    ALL_SQL_DB_ENGINE_FIXTURES,
    assert_wide_meta_non_string_types,
    assert_strict_wide_types,
    assert_wide_result,
    build_wide_query,
    build_wide_rows,
    dialect_family,
    drop_table,
    seed_wide_table,
    skip_if_mssql_driver_missing,
    table_name,
)


pytestmark = pytest.mark.docker_required


def _quoted_alias(name: str, family: str) -> str:
    if family == "mysql":
        return f"`{name}`"
    if family == "mssql":
        return f"[{name}]"
    return f'"{name}"'


@pytest.mark.parametrize("engine_fixture", ALL_SQL_DB_ENGINE_FIXTURES)
def test_read_query_from_db_v3_wide_nullable_across_all_databases(
    engine_fixture: str,
    request: pytest.FixtureRequest,
) -> None:
    skip_if_mssql_driver_missing(engine_fixture)
    engine: sa.Engine = request.getfixturevalue(engine_fixture)
    target_table = table_name("query_wide", engine)
    rows = build_wide_rows(36)
    seed_wide_table(engine, target_table, rows)

    family = dialect_family(engine)
    query = build_wide_query(target_table, family)

    try:
        node = ReadQueryFromDBV3(
            user_id="user",
            project_id="project",
            task_id="task",
            node_id="node-read-query-v3",
            connection=engine,
            sql_code=query,
            partition_col="id",
            npartitions=6,
        )
        node.process()

        assert node.output.known_divisions is True
        assert_wide_meta_non_string_types(node.output._meta, family)
        result = node.output.compute().reset_index(drop=True)
        assert_wide_result(result, expected_rows=len(rows))
        assert_strict_wide_types(result, family)
    finally:
        drop_table(engine, target_table)


@pytest.mark.parametrize("engine_fixture", ALL_SQL_DB_ENGINE_FIXTURES)
def test_read_query_from_db_v3_preserves_exact_alias_case_across_all_databases(
    engine_fixture: str,
    request: pytest.FixtureRequest,
) -> None:
    skip_if_mssql_driver_missing(engine_fixture)
    engine: sa.Engine = request.getfixturevalue(engine_fixture)
    target_table = table_name("query_alias_case", engine)
    rows = build_wide_rows(12)
    seed_wide_table(engine, target_table, rows)

    family = dialect_family(engine)
    period_alias = _quoted_alias("MiXeDPeriod", family)
    source_alias = _quoted_alias("SourceField", family)
    kontragent_alias = _quoted_alias("KontragentField", family)
    query = (
        f"SELECT id AS {period_alias}, str_col AS {source_alias}, int_col AS {kontragent_alias} "
        f"FROM {target_table} ORDER BY id"
    )

    try:
        node = ReadQueryFromDBV3(
            user_id="user",
            project_id="project",
            task_id="task",
            node_id="node-read-query-v3-alias-case",
            connection=engine,
            sql_code=query,
            partition_col="mixedperiod",
            npartitions=4,
        )

        node.process()

        assert list(node.output._meta.columns) == ["MiXeDPeriod", "SourceField", "KontragentField"]
        result = node.output.compute().reset_index(drop=True)
        assert list(result.columns) == ["MiXeDPeriod", "SourceField", "KontragentField"]
        assert result["MiXeDPeriod"].tolist() == list(range(1, len(rows) + 1))
        assert result["SourceField"].iloc[0] == rows[0]["str_col"]
        assert result["KontragentField"].iloc[0] == rows[0]["int_col"]
    finally:
        drop_table(engine, target_table)


def test_read_query_from_db_v3_oracle_quoted_aliases_are_supported(
    request: pytest.FixtureRequest,
) -> None:
    engine: sa.Engine = request.getfixturevalue("oracle_test_engine")
    target_table = table_name("query_aliases", engine)
    rows = build_wide_rows(12)
    seed_wide_table(engine, target_table, rows)

    query = (
        f'SELECT id AS "Source", str_col AS "Kontragent" '
        f"FROM {target_table} ORDER BY id"
    )

    try:
        node = ReadQueryFromDBV3(
            user_id="user",
            project_id="project",
            task_id="task",
            node_id="node-read-query-v3-oracle-aliases",
            connection=engine,
            sql_code=query,
            partition_col="Source",
            npartitions=4,
        )

        node.process()

        assert list(node.output._meta.columns) == ["Source", "Kontragent"]
        result = node.output.compute().reset_index(drop=True)
        assert list(result.columns) == ["Source", "Kontragent"]
        assert result["Source"].tolist() == list(range(1, len(rows) + 1))
        assert result["Kontragent"].iloc[0] == rows[0]["str_col"]
    finally:
        drop_table(engine, target_table)


def test_read_query_from_db_v3_oracle_mixed_display_and_exact_sql_names(
    request: pytest.FixtureRequest,
) -> None:
    engine: sa.Engine = request.getfixturevalue("oracle_test_engine")
    target_table = table_name("query_period", engine)
    rows = build_wide_rows(12)
    seed_wide_table(engine, target_table, rows)

    query = (
        f'SELECT id AS PERIOD, str_col AS "Source", int_col AS "Kontragent" '
        f"FROM {target_table} ORDER BY PERIOD"
    )

    try:
        node = ReadQueryFromDBV3(
            user_id="user",
            project_id="project",
            task_id="task",
            node_id="node-read-query-v3-oracle-period",
            connection=engine,
            sql_code=query,
            partition_col="period",
            npartitions=4,
        )

        node.process()

        assert list(node.output._meta.columns) == ["PERIOD", "Source", "Kontragent"]
        result = node.output.compute().reset_index(drop=True)
        assert list(result.columns) == ["PERIOD", "Source", "Kontragent"]
        assert result["PERIOD"].tolist() == list(range(1, len(rows) + 1))
        assert result["Source"].iloc[0] == rows[0]["str_col"]
        assert result["Kontragent"].iloc[0] == rows[0]["int_col"]
    finally:
        drop_table(engine, target_table)
