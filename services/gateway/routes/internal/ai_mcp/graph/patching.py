"""Apply requested edits to an owned working copy, collecting structural errors."""

from .diagnostics import Diagnostics
from .inputs import canonical_input
from .node_policies import GENERIC_CODE_NODES
from .references import ResolvedNode, ResolvedPatch
from .schemas import UpdateNodeSchema
from .state import EdgeState, GraphChanges, GraphState, NodeState


def apply_patch_to_state(
    graph: GraphState,
    patch: ResolvedPatch,
    diagnostics: Diagnostics,
) -> GraphChanges:
    changes = GraphChanges(
        created_node_ids={node.id for node in patch.add_nodes},
        updated_node_ids={node.id for node in patch.update_nodes},
        deleted_node_ids=set(patch.delete_node_ids),
    )
    _delete_nodes(graph, changes, diagnostics)
    for update in patch.update_nodes:
        _update_node(graph, update, changes, diagnostics)
    for addition in patch.add_nodes:
        _add_node(graph, addition, changes, diagnostics)
    _delete_edges(graph, patch, changes, diagnostics)
    _add_edges(graph, patch, changes, diagnostics)
    return changes


def _check_subgraph(graph: GraphState, subgraph_id: str | None, diagnostics: Diagnostics) -> None:
    if subgraph_id is not None and subgraph_id not in graph.subgraphs:
        diagnostics.errors.append({"code": "UNKNOWN_SUBGRAPH", "subgraph_id": subgraph_id})


def _delete_nodes(graph: GraphState, changes: GraphChanges, diagnostics: Diagnostics) -> None:
    unknown = sorted(changes.deleted_node_ids - graph.nodes.keys())
    if unknown:
        diagnostics.errors.append({"code": "UNKNOWN_NODE", "node_ids": unknown})
    for node_id in changes.deleted_node_ids:
        graph.nodes.pop(node_id, None)


def _apply_inputs(
    node: NodeState,
    update: ResolvedNode | UpdateNodeSchema,
    diagnostics: Diagnostics,
) -> None:
    for name, value in (update.inputs or {}).items():
        if value is None:
            node.inputs.pop(name, None)
            continue
        try:
            node.inputs[name] = canonical_input(value)
        except ValueError as exc:
            diagnostics.errors.append(
                {"code": "INVALID_INPUT", "node_id": node.id, "message": str(exc)}
            )


def _update_node(
    graph: GraphState,
    update: UpdateNodeSchema,
    changes: GraphChanges,
    diagnostics: Diagnostics,
) -> None:
    node = graph.nodes.get(update.id)
    if node is None:
        diagnostics.errors.append({"code": "UNKNOWN_NODE", "node_id": update.id})
        return
    fields = update.model_fields_set
    if "node_type" in fields and update.node_type is not None:
        node.node_type = update.node_type
    if "display_name" in fields:
        node.display_name = update.display_name or node.node_type
    if "comment" in fields:
        node.comment = update.comment
    if "subgraph_id" in fields:
        _check_subgraph(graph, update.subgraph_id, diagnostics)
        node.subgraph_id = update.subgraph_id
    if "store_enabled" in fields and update.store_enabled is not None:
        node.store_enabled = update.store_enabled
    if "inputs" in fields and update.inputs is not None:
        _apply_inputs(node, update, diagnostics)
    if node.node_type in GENERIC_CODE_NODES:
        changes.touched_code_node_ids.add(node.id)


def _add_node(
    graph: GraphState,
    addition: ResolvedNode,
    changes: GraphChanges,
    diagnostics: Diagnostics,
) -> None:
    if addition.id in graph.nodes:
        diagnostics.errors.append({"code": "DUPLICATE_NODE_ID", "node_id": addition.id})
        return
    _check_subgraph(graph, addition.subgraph_id, diagnostics)
    node = NodeState(
        id=addition.id,
        subgraph_id=addition.subgraph_id,
        node_type=addition.node_type,
        display_name=addition.display_name or addition.node_type,
        comment=addition.comment,
        store_enabled=addition.store_enabled,
    )
    _apply_inputs(node, addition, diagnostics)
    graph.nodes[node.id] = node
    if node.node_type in GENERIC_CODE_NODES:
        changes.touched_code_node_ids.add(node.id)


def _delete_edges(
    graph: GraphState,
    patch: ResolvedPatch,
    changes: GraphChanges,
    diagnostics: Diagnostics,
) -> None:
    implicit_deletes = {
        edge.id
        for edge in graph.edges.values()
        if edge.source in changes.deleted_node_ids or edge.target in changes.deleted_node_ids
    }
    explicit_deletes = set(patch.delete_connection_ids)
    changes.deleted_edge_ids = explicit_deletes | implicit_deletes
    unknown = sorted(explicit_deletes - graph.edges.keys())
    if unknown:
        diagnostics.errors.append({"code": "UNKNOWN_CONNECTION", "connection_ids": unknown})
    for edge_id in changes.deleted_edge_ids:
        graph.edges.pop(edge_id, None)


def _add_edges(
    graph: GraphState,
    patch: ResolvedPatch,
    changes: GraphChanges,
    diagnostics: Diagnostics,
) -> None:
    for addition in patch.add_connections:
        if addition.id in graph.edges:
            diagnostics.errors.append(
                {"code": "DUPLICATE_CONNECTION_ID", "connection_id": addition.id}
            )
            continue
        if addition.source not in graph.nodes or addition.target not in graph.nodes:
            diagnostics.errors.append(
                {"code": "UNKNOWN_CONNECTION_NODE", "connection_id": addition.id}
            )
            continue
        subgraph_id = addition.subgraph_id
        source_group = graph.nodes[addition.source].subgraph_id
        target_group = graph.nodes[addition.target].subgraph_id
        if subgraph_id is None and source_group == target_group:
            subgraph_id = source_group
        _check_subgraph(graph, subgraph_id, diagnostics)
        graph.edges[addition.id] = EdgeState(
            id=addition.id,
            source=addition.source,
            target=addition.target,
            source_handle=f"output-{addition.source_output}",
            target_handle=f"input-{addition.target_input}",
            subgraph_id=subgraph_id,
        )
        changes.created_edge_ids.add(addition.id)
