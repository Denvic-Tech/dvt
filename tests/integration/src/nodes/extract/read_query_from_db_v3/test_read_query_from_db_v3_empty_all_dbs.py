from __future__ import annotations

import pytest
import sqlalchemy as sa

from src.nodes.extract.read_query_from_db_v3 import ReadQueryFromDBV3
from tests.integration.src.nodes.extract.read_db_v3_matrix_helpers import (
    ALL_SQL_DB_ENGINE_FIXTURES,
    WIDE_COLUMNS,
    assert_wide_meta_non_string_types,
    build_wide_query,
    dialect_family,
    drop_table,
    seed_empty_wide_table,
    skip_if_mssql_driver_missing,
    table_name,
)


pytestmark = pytest.mark.docker_required


@pytest.mark.parametrize("engine_fixture", ALL_SQL_DB_ENGINE_FIXTURES)
def test_read_query_from_db_v3_empty_table_preserves_meta_types_across_all_databases(
    engine_fixture: str,
    request: pytest.FixtureRequest,
) -> None:
    skip_if_mssql_driver_missing(engine_fixture)
    engine: sa.Engine = request.getfixturevalue(engine_fixture)
    target_table = table_name("query_empty", engine)
    seed_empty_wide_table(engine, target_table)

    family = dialect_family(engine)
    query = build_wide_query(target_table, family)

    try:
        node = ReadQueryFromDBV3(
            user_id="user",
            project_id="project",
            task_id="task",
            node_id="node-read-query-v3-empty",
            connection=engine,
            sql_code=query,
            partition_col="id",
            npartitions=4,
        )
        node.process()

        assert node.output.known_divisions is True
        assert_wide_meta_non_string_types(node.output._meta, family)

        result = node.output.compute().reset_index(drop=True)
        assert result.empty
        actual_columns = {str(column).lower() for column in result.columns}
        assert actual_columns == set(WIDE_COLUMNS)
    finally:
        drop_table(engine, target_table)
