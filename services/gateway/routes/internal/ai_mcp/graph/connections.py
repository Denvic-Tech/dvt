"""Input roles and connection dependencies shared by graph reads and validation."""

from collections.abc import Iterable
from typing import Any

from services.gateway.deps.dvt_service_files import _root_prefix

from src.modules.pipeline_graph.infra.db_models import GraphNodeRecord
from src.node_dsl import get_definition
from src.node_dsl.core.input_values import NodeInputValues, parse_node_input_value

from .state import GraphState


def input_names_with_type_suffixes(node_name: str, suffixes: tuple[str, ...]) -> set[str]:
    try:
        definition = get_definition(node_name)
    except KeyError:
        return set()
    result = set()
    for name, field in definition.input_definitions.items():
        field_types = field.type if isinstance(field.type, list) else [field.type]
        normalized_types = {
            member.strip() for item in field_types for member in str(item).upper().split(",")
        }
        if any(member.endswith(suffixes) for member in normalized_types):
            result.add(name)
    return result


def connection_input_names(node_name: str) -> set[str]:
    return input_names_with_type_suffixes(
        node_name,
        ("_CONNECTION", "_CONNECTION_ID"),
    )


def connection_object_input_names(node_name: str) -> set[str]:
    return input_names_with_type_suffixes(node_name, ("_CONNECTION",))


def is_valid_dvt_service_reference(
    raw: Any,
    *,
    project_id: str,
    node_id: str,
    input_name: str,
) -> bool:
    if not isinstance(raw, dict) or raw.get("type") != "dvt_service_files":
        return False
    expected_id = f"dvt-service-files:{project_id}:{node_id}:{input_name}"
    properties = raw.get("properties")
    return (
        raw.get("id") == expected_id
        and isinstance(properties, dict)
        and properties.get("project_id") == project_id
        and properties.get("root_prefix") == _root_prefix(node_id, input_name)
    )


def connection_object_requires_edge(
    raw: Any,
    *,
    optional: bool,
    has_incoming_edge: bool,
    project_id: str,
    node_id: str,
    input_name: str,
    existing_dvt_reference: Any,
) -> bool:
    if has_incoming_edge:
        return False
    if (
        is_valid_dvt_service_reference(
            raw,
            project_id=project_id,
            node_id=node_id,
            input_name=input_name,
        )
        and raw == existing_dvt_reference
    ):
        return False
    return raw is not None or not optional


def analyze_graph_connection_dependencies(
    nodes: Iterable[GraphNodeRecord],
    *,
    project_id: str,
) -> tuple[set[str], list[dict[str, str]]]:
    return _analyze_connection_values(
        ((node.ui_id, node.name, node.input_values or {}) for node in nodes),
        project_id=project_id,
    )


def analyze_state_connection_dependencies(
    graph: GraphState,
    *,
    project_id: str,
) -> tuple[set[str], list[dict[str, str]]]:
    return _analyze_connection_values(
        ((node.id, node.node_type, node.inputs) for node in graph.nodes.values()),
        project_id=project_id,
    )


def _analyze_connection_values(
    nodes: Iterable[tuple[str, str, NodeInputValues]],
    *,
    project_id: str,
) -> tuple[set[str], list[dict[str, str]]]:
    connection_ids: set[str] = set()
    unresolved: list[dict[str, str]] = []
    for node_id, node_name, inputs in nodes:
        names = connection_input_names(node_name)
        object_names = connection_object_input_names(node_name)
        for name in names:
            if name not in inputs:
                continue
            value = inputs.get(name)
            try:
                parsed = parse_node_input_value(value)
            except (TypeError, ValueError):
                parsed = None
            if parsed is None:
                if value is not None:
                    unresolved.append({"node_id": node_id, "input_name": name})
                continue
            dumped = parsed.model_dump(by_alias=True, mode="json")
            raw = dumped.get("value")
            if name in object_names:
                if is_valid_dvt_service_reference(
                    raw,
                    project_id=project_id,
                    node_id=node_id,
                    input_name=name,
                ):
                    continue
                if raw is not None or dumped.get("__dvt_type") != "const":
                    unresolved.append({"node_id": node_id, "input_name": name})
                continue
            if dumped.get("__dvt_type") != "const":
                unresolved.append({"node_id": node_id, "input_name": name})
            elif isinstance(raw, str) and raw:
                connection_ids.add(raw)
            elif is_valid_dvt_service_reference(
                raw,
                project_id=project_id,
                node_id=node_id,
                input_name=name,
            ):
                continue
            elif raw is not None:
                unresolved.append({"node_id": node_id, "input_name": name})
    return connection_ids, unresolved
