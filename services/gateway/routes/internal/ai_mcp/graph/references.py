"""Resolve local references, render diagnostics, then materialize validated identities."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from ..errors import AIMCPHTTPError
from .schemas import (
    AddConnectionSchema,
    AddNodeSchema,
    GraphPatchSchema,
    NewNodeReference,
    NodeReference,
    UpdateNodeSchema,
)

if TYPE_CHECKING:
    from services.gateway.routes.project.graph.graph_operations import GraphOperationsAggregated


class ResolvedNode(AddNodeSchema):
    id: str


@dataclass
class ResolvedConnection:
    id: str
    source: str
    source_output: str
    target: str
    target_input: str
    subgraph_id: str | None


@dataclass
class TemporaryIds:
    used: set[str]

    def allocate(self, kind: str, index: int) -> str:
        value = f"__mcp_{kind}_{index:08d}__"
        while value in self.used:
            value += "_"
        self.used.add(value)
        return value


@dataclass
class ResolvedPatch:
    add_nodes: list[ResolvedNode]
    update_nodes: list[UpdateNodeSchema]
    delete_node_ids: list[str]
    add_connections: list[ResolvedConnection]
    delete_connection_ids: list[str]
    node_ids_by_ref: dict[str, str]

    @cached_property
    def refs_by_node_id(self) -> dict[str, str]:
        return {node_id: ref for ref, node_id in self.node_ids_by_ref.items()}

    @cached_property
    def connection_indexes(self) -> dict[str, int]:
        return {edge.id: index for index, edge in enumerate(self.add_connections)}

    def node_reference(self, node_id: str) -> dict[str, str]:
        if node_id in self.refs_by_node_id:
            return {"ref": self.refs_by_node_id[node_id]}
        return {"id": node_id}

    def diagnostics(self, value: Any) -> Any:
        return _render_diagnostic(value, self)

    def materialize(self, payload: GraphOperationsAggregated) -> dict[str, str]:
        """Only the validated save payload is mutated; input values remain untouched."""
        permanent = {temporary: f"node_{uuid4()}" for temporary in self.node_ids_by_ref.values()}
        for node in payload.nodes_to_create:
            node.id = permanent[node.id]
        for edge in payload.edges_to_create:
            edge.id = f"edge_{uuid4()}"
            edge.source = permanent.get(edge.source, edge.source)
            edge.target = permanent.get(edge.target, edge.target)
        return {ref: permanent[temporary] for ref, temporary in self.node_ids_by_ref.items()}


def _render_diagnostic(value: Any, patch: ResolvedPatch) -> Any:
    if isinstance(value, list):
        return [_render_diagnostic(child, patch) for child in value]
    if isinstance(value, dict):
        return _render_diagnostic_mapping(value, patch)
    if isinstance(value, str):
        for node_id, ref in patch.refs_by_node_id.items():
            value = value.replace(node_id, f"ref:{ref}")
        for edge_id, index in patch.connection_indexes.items():
            value = value.replace(edge_id, f"add_connections[{index}]")
    return value


def _render_diagnostic_mapping(value: dict[str, Any], patch: ResolvedPatch) -> dict[str, Any]:
    result = {}
    for key, child in value.items():
        if key == "node_id" and isinstance(child, str) and child in patch.refs_by_node_id:
            result["node_ref"] = patch.refs_by_node_id[child]
        elif key == "node_ids" and isinstance(child, list):
            result["nodes"] = [patch.node_reference(node_id) for node_id in child]
        elif (
            key == "connection_id" and isinstance(child, str) and child in patch.connection_indexes
        ):
            result["connection_index"] = patch.connection_indexes[child]
        else:
            result[_render_diagnostic(key, patch)] = _render_diagnostic(child, patch)
    return result


def _resolve_nodes(
    additions: list[AddNodeSchema],
    temporary: TemporaryIds,
    errors: list[dict[str, Any]],
) -> tuple[list[ResolvedNode], dict[str, str]]:
    nodes = []
    refs = {}
    for index, node in enumerate(additions):
        if node.ref in refs:
            errors.append({"code": "DUPLICATE_NODE_REF", "node_ref": node.ref})
            continue
        refs[node.ref] = temporary.allocate("node", index)
        nodes.append(ResolvedNode(**node.model_dump(), id=refs[node.ref]))
    return nodes, refs


def _resolve_endpoint(
    reference: NodeReference,
    *,
    refs: dict[str, str],
    existing_ids: set[str],
    deleted_ids: set[str],
    connection_index: int,
    side: str,
    errors: list[dict[str, Any]],
) -> str | None:
    location = {"connection_index": connection_index, "endpoint": side}
    if isinstance(reference, NewNodeReference):
        node_id = refs.get(reference.ref)
        if node_id is None:
            errors.append({"code": "UNKNOWN_NODE_REF", "node_ref": reference.ref, **location})
        return node_id
    if reference.id not in existing_ids or reference.id in deleted_ids:
        errors.append({"code": "UNKNOWN_CONNECTION_NODE", "node_id": reference.id, **location})
        return None
    return reference.id


def _resolve_connections(
    additions: list[AddConnectionSchema],
    *,
    refs: dict[str, str],
    existing_ids: set[str],
    deleted_ids: set[str],
    temporary: TemporaryIds,
    errors: list[dict[str, Any]],
) -> list[ResolvedConnection]:
    connections = []
    for index, edge in enumerate(additions):
        source = _resolve_endpoint(
            edge.source,
            side="source",
            refs=refs,
            existing_ids=existing_ids,
            deleted_ids=deleted_ids,
            connection_index=index,
            errors=errors,
        )
        target = _resolve_endpoint(
            edge.target,
            side="target",
            refs=refs,
            existing_ids=existing_ids,
            deleted_ids=deleted_ids,
            connection_index=index,
            errors=errors,
        )
        if source is not None and target is not None:
            connections.append(
                ResolvedConnection(
                    id=temporary.allocate("edge", index),
                    source=source,
                    target=target,
                    source_output=edge.source_output,
                    target_input=edge.target_input,
                    subgraph_id=edge.subgraph_id,
                )
            )
    return connections


def resolve_patch(patch: GraphPatchSchema, node_ids: set[str], edge_ids: set[str]) -> ResolvedPatch:
    errors: list[dict[str, Any]] = []
    temporary = TemporaryIds(node_ids | edge_ids)
    additions, refs = _resolve_nodes(patch.add_nodes, temporary, errors)
    connections = _resolve_connections(
        patch.add_connections,
        refs=refs,
        existing_ids=node_ids,
        deleted_ids=set(patch.delete_node_ids),
        temporary=temporary,
        errors=errors,
    )
    if errors:
        raise AIMCPHTTPError(
            422,
            "GRAPH_VALIDATION_FAILED",
            "Graph references did not pass validation.",
            details={"errors": errors},
        )
    return ResolvedPatch(
        add_nodes=additions,
        update_nodes=patch.update_nodes,
        delete_node_ids=patch.delete_node_ids,
        add_connections=connections,
        delete_connection_ids=patch.delete_connection_ids,
        node_ids_by_ref=refs,
    )
