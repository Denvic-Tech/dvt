import pytest
from tests.integration.fixtures.db_comments import (
    COLUMN_COMMENT,
    COMMENT_DIALECTS,
    TABLE_COMMENT,
)

from src.nodes.extract.read_table_from_db_v3 import ReadTableFromDBV3

pytest_plugins = ["tests.integration.fixtures.db_comments"]
pytestmark = pytest.mark.docker_required


@pytest.mark.parametrize("comments_engine", COMMENT_DIALECTS, indirect=True)
@pytest.mark.asyncio
async def test_native_comments_survive_full_read_and_metadata_only(
    comments_engine, commented_table
):
    def node():
        return ReadTableFromDBV3(
            user_id="u",
            project_id="p",
            task_id="t",
            node_id="n",
            connection=comments_engine,
            table_name=commented_table.name,
            columns=["id", "value"],
            partition_col="id",
            npartitions=1,
        )

    reader = node()
    reader.process()
    result = reader.output.compute()
    assert len(result) == 2
    full = (await reader.resolve_metadata())["output"]
    assert full.comment == TABLE_COMMENT
    assert {column.name: column.comment for column in full.columns} == {
        "id": COLUMN_COMMENT,
        "value": None,
    }
    metadata_reader = node()
    await metadata_reader.process_metadata()
    inferred = (await metadata_reader.resolve_metadata())["output"]
    assert inferred.comment == TABLE_COMMENT
    assert {column.name: column.comment for column in inferred.columns} == {
        "id": COLUMN_COMMENT,
        "value": None,
    }
    assert metadata_reader.output._meta.empty
