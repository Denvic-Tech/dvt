from __future__ import annotations

from collections import deque
from collections.abc import Sequence

from src import enums
from src.modules.pipeline_graph.infra.db_models import GraphEdgeRecord, GraphNodeRecord
from src.node_dsl.registry import nodes as nodes_registry


def collect_affected_terminal_node_ids(
    *,
    nodes: Sequence[GraphNodeRecord],
    edges: Sequence[GraphEdgeRecord],
    seed_node_ids: Sequence[str],
) -> list[str]:
    node_by_id = {node.ui_id: node for node in nodes}
    outgoing_edges_map: dict[str, list[GraphEdgeRecord]] = {}

    for edge in edges:
        outgoing_edges_map.setdefault(edge.source, []).append(edge)

    affected_node_ids: set[str] = set()
    queue = deque(node_id for node_id in seed_node_ids if node_id in node_by_id)
    while queue:
        node_id = queue.popleft()
        if node_id in affected_node_ids:
            continue

        affected_node_ids.add(node_id)
        for edge in outgoing_edges_map.get(node_id, []):
            if edge.target not in affected_node_ids:
                queue.append(edge.target)

    target_node_ids: list[str] = []
    for node in nodes:
        if node.ui_id not in affected_node_ids or node.type == enums.NodeType.WIDGET.value.lower():
            continue

        try:
            node_class = nodes_registry.get(node.name)
        except Exception:
            continue

        is_output_node = bool(getattr(node_class, "OUTPUT_NODE", False))
        is_terminal_node = node.ui_id not in outgoing_edges_map
        if is_output_node or is_terminal_node:
            target_node_ids.append(node.ui_id)

    return target_node_ids
