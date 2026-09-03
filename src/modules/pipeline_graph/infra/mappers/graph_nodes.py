from collections.abc import Collection, Iterable, Mapping
from typing import Any

from pydantic_core import PydanticUndefined

from src.modules.pipeline_graph.infra.db_models import GraphNodeRecord
from src.utils.common import getattr_deep

from ..schemas.graph_node import (
    GraphNodeData,
    GraphNodeUISchema,
    GraphNodeUIUpdateSchema,
    Position,
)

persistent_to_ui_fields = {
    GraphNodeRecord.ui_id: "id",
    GraphNodeRecord.type: "type",
    GraphNodeRecord.subgraph_id: "subgraphId",

    GraphNodeRecord.position_x: "position.x",
    GraphNodeRecord.position_y: "position.y",

    GraphNodeRecord.selected: "selected",

    GraphNodeRecord.name: "data.name",
    GraphNodeRecord.display_name: "data.displayName",
    GraphNodeRecord.store_enabled: "data.storeEnabled",
    GraphNodeRecord.show_signal_io: "data.showSignalIo",
    GraphNodeRecord.show_variables_io: "data.showVariablesIo",
    GraphNodeRecord.comment: "data.comment",
    GraphNodeRecord.input_values: "data.inputValues",
}

ui_to_persistent_fields = {v: k for k, v in persistent_to_ui_fields.items()}


def iter_dict_items(
    data: Mapping[str, Any],
    *,
    parent: str | None = None,
    sep: str = ".",
    stop_keys: Collection[str] | None = None,
) -> Iterable[tuple[str, Any]]:
    stop_keys = stop_keys or ()

    for key, value in data.items():
        full_key = f"{parent}{sep}{key}" if parent else str(key)

        if isinstance(value, Mapping) and key not in stop_keys:
            yield from iter_dict_items(
                value,
                parent=full_key,
                sep=sep,
                stop_keys=stop_keys,
            )
        else:
            yield full_key, value


def to_ui(node: GraphNodeRecord) -> GraphNodeUISchema:
    return GraphNodeUISchema(
        id=node.ui_id,
        type=node.type,
        subgraphId=node.subgraph_id,
        data=GraphNodeData(
            name=node.name,
            displayName=node.display_name,
            comment=node.comment,
            inputValues=node.input_values or {},
            storeEnabled=node.store_enabled,
            showSignalIo=node.show_signal_io,
            showVariablesIo=node.show_variables_io,
        ),
        position=Position(x=node.position_x, y=node.position_y),
    )


def to_persistent(
    node: GraphNodeUISchema | GraphNodeUIUpdateSchema,
    project_id: str,
    user_id: str,
    organization_id: str,
) -> GraphNodeRecord:
    ui_node_data = node.model_dump(exclude_unset=True)

    persistent_payload = {}

    for persistent_field, ui_field in persistent_to_ui_fields.items():
        value = getattr_deep(ui_node_data, ui_field, default=PydanticUndefined)
        if value is not PydanticUndefined:
            persistent_payload[persistent_field.name] = value

    persistent = GraphNodeRecord(
        **persistent_payload,
        project_id=project_id,
        user_id=user_id,
        organization_id=organization_id,
    )

    return persistent
