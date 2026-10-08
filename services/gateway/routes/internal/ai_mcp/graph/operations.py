"""Build existing persistence commands and MCP previews from prepared state."""

from typing import Any

from services.gateway.routes.project.graph.graph_operations import GraphOperationsAggregated

from .layout.geometry import Rect
from .mappers import edge_to_ui, node_to_ui
from .references import ResolvedPatch
from .state import GraphChanges, GraphState, PositionChanges


def position_operations(positions: PositionChanges) -> GraphOperationsAggregated:
    return GraphOperationsAggregated(
        nodes_to_update=[
            {"id": node_id, "position": position.mapping()}
            for node_id, position in sorted(positions.nodes.items())
        ],
        subgraphs_to_update=[
            {"id": group_id, "position": position.mapping()}
            for group_id, position in sorted(positions.subgraphs.items())
        ],
    )


def build_operations(
    graph: GraphState,
    changes: GraphChanges,
    positions: PositionChanges,
) -> GraphOperationsAggregated:
    payload = position_operations(positions)
    return GraphOperationsAggregated(
        nodes_to_delete=[{"id": node_id} for node_id in sorted(changes.deleted_node_ids)],
        nodes_to_create=[
            node_to_ui(graph.nodes[node_id])
            for node_id in sorted(changes.created_node_ids)
            if node_id in graph.nodes
        ],
        nodes_to_update=[
            node_to_ui(graph.nodes[node_id]).model_dump(mode="json")
            for node_id in sorted(changes.updated_node_ids)
            if node_id in graph.nodes
        ]
        + [
            item
            for item in payload.nodes_to_update
            if item.id not in changes.created_node_ids | changes.updated_node_ids
        ],
        subgraphs_to_update=payload.subgraphs_to_update,
        edges_to_delete=[{"id": edge_id} for edge_id in sorted(changes.deleted_edge_ids)],
        edges_to_create=[
            edge_to_ui(edge) for edge in graph.edges.values() if edge.id in changes.created_edge_ids
        ],
    )


def patch_preview(
    payload: GraphOperationsAggregated,
    references: ResolvedPatch,
    positions: PositionChanges,
    bounds: Rect,
) -> dict[str, Any]:
    return {
        "created_node_refs": list(references.node_ids_by_ref),
        "changes": {
            "nodes_created": len(payload.nodes_to_create),
            "nodes_updated": len(payload.nodes_to_update),
            "nodes_deleted": len(payload.nodes_to_delete),
            "connections_created": len(payload.edges_to_create),
            "connections_deleted": len(payload.edges_to_delete),
        },
        "layout": {
            "moved_nodes": [
                references.node_reference(node_id) for node_id in sorted(positions.nodes)
            ],
            "moved_subgraph_ids": sorted(positions.subgraphs),
            "bounds": bounds.mapping(),
        },
    }
