from pydantic_core import PydanticUndefined

from src.modules.pipeline_graph.infra.db_models import GraphEdgeRecord
from src.utils.common import getattr_deep

from ..schemas.graph_edge import (
    GraphEdgeUISchema,
    GraphEdgeUpdateUISchema,
)

persistent_to_ui_fields = {
    GraphEdgeRecord.ui_id: "id",
    GraphEdgeRecord.type: "type",
    GraphEdgeRecord.subgraph_id: "subgraphId",

    GraphEdgeRecord.source: "source",
    GraphEdgeRecord.source_handle: "sourceHandle",

    GraphEdgeRecord.target: "target",
    GraphEdgeRecord.target_handle: "targetHandle",
}


def to_ui(edge: GraphEdgeRecord) -> GraphEdgeUISchema:
    return GraphEdgeUISchema(
        id=edge.ui_id,
        type=edge.type,
        subgraphId=edge.subgraph_id,

        source=edge.source,
        sourceHandle=edge.source_handle,

        target=edge.target,
        targetHandle=edge.target_handle,
    )


def to_persistent(edge: GraphEdgeUISchema | GraphEdgeUpdateUISchema,
                  project_id: str, user_id: str, organization_id: str) -> GraphEdgeRecord:
    ui_edge_data = edge.model_dump(exclude_unset=True)

    persistent_payload = {}
    for persistent_field, ui_field in persistent_to_ui_fields.items():
        value = getattr_deep(ui_edge_data, ui_field, default=PydanticUndefined)
        if value is not PydanticUndefined:
            persistent_payload[persistent_field.name] = value

    persistent = GraphEdgeRecord(
        **persistent_payload,
        project_id=project_id,
        user_id=user_id,
        organization_id=organization_id,
    )

    return persistent
