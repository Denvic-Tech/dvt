"""Paginated MCP graph representation and scoped connection annotations."""

from typing import Any

from src.node_dsl.core.input_values import parse_node_input_value

from ..access import get_accessible_connection
from ..auth import MCPPrincipal
from ..errors import AIMCPHTTPError
from ..pagination import decode_cursor, encode_cursor
from .connections import (
    analyze_state_connection_dependencies,
    connection_input_names,
    is_valid_dvt_service_reference,
)
from .inputs import ai_input
from .mappers import subgraph_to_ui
from .state import GraphSnapshot, GraphState, NodeState


async def accessible_connection_ids(
    graph: GraphState,
    principal: MCPPrincipal,
    project_id: str,
) -> set[str]:
    connection_ids, _ = analyze_state_connection_dependencies(graph, project_id=project_id)
    accessible = set()
    for connection_id in connection_ids:
        try:
            await get_accessible_connection(principal, connection_id)
            accessible.add(connection_id)
        except AIMCPHTTPError:
            pass
    return accessible


def _node_inputs(
    node: NodeState,
    project_id: str,
    accessible: set[str],
) -> dict[str, Any]:
    connection_inputs = connection_input_names(node.node_type)
    inputs = {}
    for name, value in node.inputs.items():
        if name in connection_inputs:
            parsed = parse_node_input_value(value)
            raw = None if parsed is None else parsed.model_dump(by_alias=True).get("value")
            if isinstance(raw, dict) and raw.get("type") == "dvt_service_files":
                connection_id = raw.get("id")
                inputs[name] = {
                    "kind": "connection_ref",
                    "connection_id": connection_id if isinstance(connection_id, str) else None,
                    "accessible": is_valid_dvt_service_reference(
                        raw,
                        project_id=project_id,
                        node_id=node.id,
                        input_name=name,
                    ),
                }
                continue
            if isinstance(raw, str) and raw not in accessible:
                inputs[name] = {
                    "kind": "connection_ref",
                    "connection_id": raw,
                    "accessible": False,
                }
                continue
        inputs[name] = ai_input(value, accessible_connection_ids=accessible)
    return inputs


def _node_payload(node: NodeState, project_id: str, accessible: set[str]) -> dict[str, Any]:
    return {
        "id": node.id,
        "node_type": node.node_type,
        "ui_type": node.ui_type,
        "display_name": node.display_name,
        "comment": node.comment,
        "position": node.position.mapping(),
        "subgraph_id": node.subgraph_id,
        "store_enabled": node.store_enabled,
        "inputs": _node_inputs(node, project_id, accessible),
    }


async def graph_page(
    snapshot: GraphSnapshot,
    *,
    project_id: str,
    revision: int,
    principal: MCPPrincipal,
    cursor: str | None,
    limit: int,
) -> dict[str, Any]:
    graph = snapshot.state
    offset = decode_cursor(cursor)
    limit = max(1, min(limit, 200))
    ordered_nodes = sorted(graph.nodes.values(), key=lambda node: node.id)
    page_nodes = ordered_nodes[offset : offset + limit]
    page_ids = {node.id for node in page_nodes}
    accessible = await accessible_connection_ids(graph, principal, project_id)
    page_edges = [edge for edge in graph.edges.values() if edge.target in page_ids]
    return {
        "project_id": project_id,
        "graph_revision": revision,
        "graph_etag": snapshot.etag,
        "nodes": [_node_payload(node, project_id, accessible) for node in page_nodes],
        "connections": [
            {
                "id": edge.id,
                "source": edge.source,
                "source_output": edge.source_output,
                "target": edge.target,
                "target_input": edge.target_input,
                "subgraph_id": edge.subgraph_id,
            }
            for edge in sorted(page_edges, key=lambda edge: edge.id)
        ],
        "subgraphs": [
            subgraph_to_ui(group).model_dump(mode="json") for group in graph.subgraphs.values()
        ],
        "next_cursor": encode_cursor(offset + len(page_nodes), len(ordered_nodes)),
    }
