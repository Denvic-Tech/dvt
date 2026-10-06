"""Conversions between existing UI/ORM schemas and the preparation state."""

from src.modules.pipeline_graph.infra.schemas import (
    GraphEdgeUISchema,
    GraphNodeUISchema,
    SubgraphUISchema,
)

from .state import EdgeState, NodeState, Position, SubgraphState


def node_from_ui(node: GraphNodeUISchema) -> NodeState:
    data = node.data
    return NodeState(
        id=node.id,
        position=Position(node.position.x, node.position.y),
        subgraph_id=node.subgraphId,
        node_type=data.name,
        display_name=data.displayName,
        comment=data.comment,
        inputs=data.inputValues,
        ui_type=node.type,
        selected=node.selected,
        store_enabled=data.storeEnabled,
        show_signal_io=data.showSignalIo,
        show_variables_io=data.showVariablesIo,
    )


def node_to_ui(node: NodeState) -> GraphNodeUISchema:
    if node.position is None:
        raise ValueError("A node must be laid out before serialization.")
    return GraphNodeUISchema(
        id=node.id,
        type=node.ui_type,
        subgraphId=node.subgraph_id,
        position=node.position.mapping(),
        selected=node.selected,
        data={
            "name": node.node_type,
            "displayName": node.display_name,
            "comment": node.comment,
            "inputValues": node.inputs,
            "storeEnabled": node.store_enabled,
            "showSignalIo": node.show_signal_io,
            "showVariablesIo": node.show_variables_io,
        },
    )


def edge_from_ui(edge: GraphEdgeUISchema) -> EdgeState:
    return EdgeState(
        id=edge.id,
        source=edge.source,
        target=edge.target,
        source_handle=edge.sourceHandle,
        target_handle=edge.targetHandle,
        subgraph_id=edge.subgraphId,
        ui_type=edge.type,
    )


def edge_to_ui(edge: EdgeState) -> GraphEdgeUISchema:
    return GraphEdgeUISchema(
        id=edge.id,
        type=edge.ui_type,
        source=edge.source,
        target=edge.target,
        sourceHandle=edge.source_handle,
        targetHandle=edge.target_handle,
        subgraphId=edge.subgraph_id,
    )


def subgraph_from_ui(group: SubgraphUISchema) -> SubgraphState:
    return SubgraphState(
        id=group.id,
        position=Position(group.position.x, group.position.y),
        expanded=group.expanded,
        name=group.data.name,
        display_name=group.data.displayName,
        color=group.data.color,
        comment=group.data.comment,
        ui_type=group.type,
        selected=group.selected,
    )


def subgraph_to_ui(group: SubgraphState) -> SubgraphUISchema:
    return SubgraphUISchema(
        id=group.id,
        type=group.ui_type,
        position=group.position.mapping(),
        selected=group.selected,
        expanded=group.expanded,
        data={
            "name": group.name,
            "displayName": group.display_name,
            "color": group.color,
            "comment": group.comment,
        },
    )
