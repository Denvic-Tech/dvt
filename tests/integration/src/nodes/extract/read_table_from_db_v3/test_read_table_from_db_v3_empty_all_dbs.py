from __future__ import annotations

import pytest
import sqlalchemy as sa

from src.nodes.extract.read_table_from_db_v3 import ReadTableFromDBV3
from tests.integration.src.nodes.extract.read_db_v3_matrix_helpers import (
    ALL_SQL_DB_ENGINE_FIXTURES,
    EXPECTED_WIDE_TYPES_BY_FAMILY,
    WIDE_COLUMNS,
    assert_wide_meta_non_string_types,
    dialect_family,
    drop_table,
    seed_empty_wide_table,
    skip_if_mssql_driver_missing,
    table_name,
)


pytestmark = pytest.mark.docker_required


@pytest.mark.parametrize("engine_fixture", ALL_SQL_DB_ENGINE_FIXTURES)
def test_read_table_from_db_v3_empty_table_preserves_meta_types_across_all_databases(
    engine_fixture: str,
    request: pytest.FixtureRequest,
) -> None:
    skip_if_mssql_driver_missing(engine_fixture)
    engine: sa.Engine = request.getfixturevalue(engine_fixture)
    target_table = table_name("table_empty", engine)
    seed_empty_wide_table(engine, target_table)

    try:
        node = ReadTableFromDBV3(
            user_id="user",
            project_id="project",
            task_id="task",
            node_id="node-read-table-v3-empty",
            connection=engine,
            table_name=target_table,
            database_name=None,
            schema_name=None,
            columns=WIDE_COLUMNS,
            partition_col="id",
            npartitions=4,
        )
        node.process()

        assert node.output.known_divisions is True
        assert_wide_meta_non_string_types(node.output._meta, dialect_family(engine))

        metadata = node.infer_metadata()["output"]
        metadata_columns = metadata.columns
        id_columns = [column for column in metadata_columns if column.name.lower() == "id"]
        assert len(id_columns) == 1
        assert id_columns[0].index is True
        expected_id_type = EXPECTED_WIDE_TYPES_BY_FAMILY[dialect_family(engine)]["id"]
        assert id_columns[0].dtype == expected_id_type
        assert len([column.name.lower() for column in metadata_columns]) == len(
            {column.name.lower() for column in metadata_columns}
        )

        result = node.output.compute().reset_index(drop=True)
        assert result.empty
        actual_columns = {str(column).lower() for column in result.columns}
        assert actual_columns == set(WIDE_COLUMNS)
    finally:
        drop_table(engine, target_table)
