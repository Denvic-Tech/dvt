import pytest

from core.types import TableSchemaMetadata

from src.modules.data_catalog import TableSchema
from src.node_dsl import IO
from src.nodes.data_mock.table_schema import GetMockTableSchema
from src.pipeline.execution_mode import PipelineExecutionMode
from src.schemas.event import NodeMetadataEvent


def _node() -> GetMockTableSchema:
    return GetMockTableSchema(
        user_id="user-1",
        project_id="project-1",
        task_id="task-1",
        node_id="mock-table-schema-1",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", [PipelineExecutionMode.FULL, PipelineExecutionMode.METADATA_ONLY])
async def test_get_mock_table_schema_returns_schema_and_metadata(mode: PipelineExecutionMode) -> None:
    node = _node()

    await node.execute(mode)
    metadata = await node.resolve_metadata()

    assert isinstance(node.schema, TableSchema)
    assert [column.name for column in node.schema.columns] == [
        "id",
        "name",
        "amount",
        "created_at",
    ]
    assert node.output_fields()["schema"].resolved_type is IO.TABLE_SCHEMA

    schema_metadata = metadata["schema"]
    assert isinstance(schema_metadata, TableSchemaMetadata)
    assert [(column.name, column.dtype) for column in schema_metadata.columns] == [
        ("id", "BIGINT"),
        ("name", "TEXT"),
        ("amount", "NUMERIC"),
        ("created_at", "TIMESTAMPTZ"),
    ]
    assert schema_metadata.columns[0].primary_key is True
    assert schema_metadata.columns[2].precision == 18
    assert schema_metadata.columns[2].scale == 2

    event = NodeMetadataEvent(
        project_id="project-1",
        task_id="task-1",
        node_id="mock-table-schema-1",
        metadata=metadata,
    )
    payload = event.model_dump(mode="json")
    restored = NodeMetadataEvent.model_validate(payload)

    assert payload["metadata"]["schema"]["type"] == "TABLE_SCHEMA"
    assert isinstance(restored.metadata["schema"], TableSchemaMetadata)
