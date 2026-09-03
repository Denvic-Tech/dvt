from __future__ import annotations

import pytest
import sqlalchemy as sa
from tests.integration.src.nodes.extract.read_db_v3_matrix_helpers import (
    ALL_SQL_DB_ENGINE_FIXTURES,
    WIDE_COLUMNS,
    assert_strict_wide_types,
    assert_wide_meta_non_string_types,
    assert_wide_result,
    build_wide_rows,
    dialect_family,
    drop_table,
    seed_wide_table,
    skip_if_mssql_driver_missing,
    table_name,
)

from core.types import DataFrameMetadata, DataType

from src.nodes.extract.read_table_from_db_v3 import ReadTableFromDBV3

pytestmark = pytest.mark.docker_required


def test_read_table_from_db_v3_infers_clickhouse_float_metadata(
    clickhouse_http_test_engine: sa.Engine,
) -> None:
    engine = clickhouse_http_test_engine
    target_table = table_name("table_float_metadata", engine)
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                f"""
                CREATE TABLE {target_table} (
                    id Int32,
                    plain_float Float64,
                    nullable_float Nullable(Float64)
                ) ENGINE = Memory
                """
            )
        )

    try:
        node = ReadTableFromDBV3(
            user_id="user",
            project_id="project",
            task_id="task",
            node_id="node-read-table-v3-metadata",
            connection=engine,
            table_name=target_table,
            database_name=None,
            schema_name=None,
            columns=["id", "plain_float", "nullable_float"],
            partition_col="id",
            npartitions=1,
        )

        output_metadata = node.infer_metadata()["output"]

        assert isinstance(output_metadata, DataFrameMetadata)
        columns = {column.name: column for column in output_metadata.columns}
        assert columns["plain_float"].dtype == DataType.FLOAT
        assert columns["plain_float"].nullable is False
        assert columns["nullable_float"].dtype == DataType.FLOAT
        assert columns["nullable_float"].nullable is True
    finally:
        drop_table(engine, target_table)


@pytest.mark.parametrize("engine_fixture", ALL_SQL_DB_ENGINE_FIXTURES)
def test_read_table_from_db_v3_wide_nullable_across_all_databases(
    engine_fixture: str,
    request: pytest.FixtureRequest,
) -> None:
    skip_if_mssql_driver_missing(engine_fixture)
    engine: sa.Engine = request.getfixturevalue(engine_fixture)
    target_table = table_name("table_wide", engine)
    rows = build_wide_rows(36)
    seed_wide_table(engine, target_table, rows)

    try:
        node = ReadTableFromDBV3(
            user_id="user",
            project_id="project",
            task_id="task",
            node_id="node-read-table-v3",
            connection=engine,
            table_name=target_table,
            database_name=None,
            schema_name=None,
            columns=WIDE_COLUMNS,
            partition_col="id",
            npartitions=6,
        )
        node.process()

        assert node.output.known_divisions is True
        assert_wide_meta_non_string_types(node.output._meta, dialect_family(engine))
        result = node.output.compute().reset_index(drop=True)
        assert_wide_result(result, expected_rows=len(rows))
        assert_strict_wide_types(result, dialect_family(engine))
    finally:
        drop_table(engine, target_table)
