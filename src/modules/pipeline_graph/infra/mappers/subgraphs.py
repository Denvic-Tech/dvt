from pydantic_core import PydanticUndefined

from src.modules.pipeline_graph.infra.db_models import SubgraphRecord
from src.utils.common import getattr_deep

from ..schemas.subgraph import (
    Position,
    SubgraphData,
    SubgraphUISchema,
    SubgraphUIUpdateSchema,
)

persistent_to_ui_fields = {
    SubgraphRecord.ui_id: "id",
    SubgraphRecord.type: "type",
    SubgraphRecord.position_x: "position.x",
    SubgraphRecord.position_y: "position.y",
    SubgraphRecord.selected: "selected",
    SubgraphRecord.expanded: "expanded",
    SubgraphRecord.name: "data.name",
    SubgraphRecord.display_name: "data.displayName",
    SubgraphRecord.comment: "data.comment",
    SubgraphRecord.color: "data.color",
}


def to_ui(subgraph: SubgraphRecord) -> SubgraphUISchema:
    return SubgraphUISchema(
        id=subgraph.ui_id,
        type=subgraph.type,
        data=SubgraphData(
            name=subgraph.name,
            displayName=subgraph.display_name,
            comment=subgraph.comment,
            color=subgraph.color,
        ),
        position=Position(x=subgraph.position_x, y=subgraph.position_y),
        selected=subgraph.selected,
        expanded=subgraph.expanded
    )


def to_persistent(
    subgraph: SubgraphUISchema | SubgraphUIUpdateSchema,
    project_id: str,
    user_id: str,
    organization_id: str,
) -> SubgraphRecord:
    ui_subgraph_data = subgraph.model_dump(exclude_unset=True)

    persistent_payload = {}
    for persistent_field, ui_field in persistent_to_ui_fields.items():
        value = getattr_deep(ui_subgraph_data, ui_field, default=PydanticUndefined)
        if value is not PydanticUndefined:
            persistent_payload[persistent_field.name] = value

    persistent = SubgraphRecord(
        **persistent_payload,
        project_id=project_id,
        user_id=user_id,
        organization_id=organization_id,
    )

    return persistent
