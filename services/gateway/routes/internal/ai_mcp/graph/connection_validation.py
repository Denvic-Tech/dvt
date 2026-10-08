"""Connection checks; access lookup is the only asynchronous validation step."""

from typing import Any

from src.node_dsl.core.input_values import NodeInputValue, parse_node_input_value
from src.schemas.node_definition import NodeDefinition

from ..access import get_accessible_connection
from ..auth import MCPPrincipal
from ..errors import AIMCPHTTPError
from .connections import (
    connection_input_names,
    connection_object_input_names,
    connection_object_requires_edge,
    is_valid_dvt_service_reference,
)
from .diagnostics import Diagnostic
from .state import GraphState, NodeState

ServiceReferences = dict[tuple[str, str], Any]


def existing_service_references(graph: GraphState, project_id: str) -> ServiceReferences:
    references = {}
    for node in graph.nodes.values():
        for input_name in connection_input_names(node.node_type):
            parsed = parse_node_input_value(node.inputs.get(input_name))
            raw = None if parsed is None else parsed.model_dump(by_alias=True).get("value")
            if is_valid_dvt_service_reference(
                raw,
                project_id=project_id,
                node_id=node.id,
                input_name=input_name,
            ):
                references[(node.id, input_name)] = raw
    return references


async def _connection_id_error(
    parsed: NodeInputValue | None,
    *,
    principal: MCPPrincipal,
    node_id: str,
    input_name: str,
    project_id: str,
    existing_reference: Any,
) -> Diagnostic | None:
    dumped = {} if parsed is None else parsed.model_dump(by_alias=True)
    raw = dumped.get("value")
    if raw is None:
        return None
    error = {"node_id": node_id, "input": input_name}
    if dumped["__dvt_type"] != "const":
        return {"code": "UNRESOLVED_CONNECTION_REFERENCE", **error}
    if isinstance(raw, str):
        try:
            await get_accessible_connection(principal, raw)
        except AIMCPHTTPError:
            return {"code": "CONNECTION_NOT_FOUND_OR_DENIED", **error}
        return None
    if (
        is_valid_dvt_service_reference(
            raw,
            project_id=project_id,
            node_id=node_id,
            input_name=input_name,
        )
        and raw == existing_reference
    ):
        return None
    return {"code": "CONNECTION_NOT_FOUND_OR_DENIED", **error}


async def validate_node_connections(
    node: NodeState,
    definition: NodeDefinition,
    *,
    principal: MCPPrincipal,
    project_id: str,
    incoming_inputs: set[tuple[str, str]],
    existing_references: ServiceReferences,
) -> list[Diagnostic]:
    errors = []
    object_inputs = connection_object_input_names(node.node_type)
    for input_name in connection_input_names(node.node_type):
        input_definition = definition.input_definitions[input_name]
        parsed = parse_node_input_value(node.inputs.get(input_name))
        existing = existing_references.get((node.id, input_name))
        if input_name not in object_inputs:
            error = await _connection_id_error(
                parsed,
                principal=principal,
                node_id=node.id,
                input_name=input_name,
                project_id=project_id,
                existing_reference=existing,
            )
            if error is not None:
                errors.append(error)
            continue
        raw = None if parsed is None else parsed.model_dump(by_alias=True).get("value")
        if connection_object_requires_edge(
            raw,
            optional=input_definition.optional,
            has_incoming_edge=(node.id, input_name) in incoming_inputs,
            project_id=project_id,
            node_id=node.id,
            input_name=input_name,
            existing_dvt_reference=existing,
        ):
            errors.append(
                {
                    "code": "CONNECTION_NODE_REQUIRED",
                    "node_id": node.id,
                    "input": input_name,
                    "message": (
                        "Connection object inputs require an incoming edge from the "
                        "matching GetExist*Connection.connection output. Put the scoped "
                        "connection ID only in that connection node's connection_id input."
                    ),
                }
            )
    return errors
