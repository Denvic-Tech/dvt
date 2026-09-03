from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict, deque
from typing import Any, Literal
from uuid import uuid4

from jinja2.exceptions import TemplateError
from pydantic import BaseModel, Field

from services.gateway.deps.dvt_service_files import _root_prefix
from services.gateway.routes.project.graph.graph_operations import (
    ApplyGraphOperationsUseCase,
    GraphOperationsAggregated,
)

from src.crud import graph as graph_crud
from src.modules.pipeline_graph.infra.db_models import (
    GraphEdgeRecord,
    GraphNodeRecord,
)
from src.modules.pipeline_graph.infra.mappers import (
    graph_edges as graph_edges_dto,
    graph_nodes as graph_nodes_dto,
    subgraphs as subgraphs_dto,
)
from src.modules.pipeline_graph.infra.schemas import (
    GraphEdgeUISchema,
    GraphNodeUISchema,
)
from src.modules.task_execution.domain.types import TaskSource
from src.node_dsl import get_definition
from src.node_dsl.core.input_values import parse_node_input_value
from src.node_dsl.input_expressions.policy import resolve_expression_policy
from src.node_dsl.input_expressions.runtime import (
    build_environment,
    ensure_template_syntax_allowed,
)
from src.pipeline.graph import build_pipeline_from_graph
from src.pipeline.validation import validate_pipeline

from .access import get_accessible_connection, get_accessible_project
from .auth import MCPPrincipal
from .context import _available_definitions
from .errors import AIMCPHTTPError
from .pagination import decode_cursor, encode_cursor

GENERIC_CODE_NODES = frozenset({"ExecutePython", "DataFrameExecCode", "ExecuteSQL"})
X_STEP = 360.0
Y_STEP = 220.0
_PROJECT_VARIABLE_RE = re.compile(
    r"project_variables(?:\.([A-Za-z_][A-Za-z0-9_]*)|\[['\"]([^'\"]+)['\"]\])"
)


class PositionSchema(BaseModel):
    x: float
    y: float


class InputValueSchema(BaseModel):
    kind: Literal["constant", "expression", "connection_ref"] = Field(
        description=(
            "connection_ref is valid for *_CONNECTION_ID inputs on GetExist*Connection nodes; "
            "consumer *_CONNECTION object inputs require graph edges."
        )
    )
    value: Any | None = None
    expression_kind: Literal["single", "template"] = "single"
    connection_id: str | None = None


class AddNodeSchema(BaseModel):
    id: str = Field(min_length=1, max_length=255)
    node_type: str = Field(min_length=1)
    display_name: str | None = None
    comment: str | None = Field(default=None, max_length=20480)
    position: PositionSchema | None = None
    subgraph_id: str | None = None
    inputs: dict[str, InputValueSchema | None] = Field(
        default_factory=dict,
        description=(
            "Initial node inputs. ReadTableFromDBV3 requires explicit partition_col and columns. "
            "Connection object inputs must be supplied by edges from GetExist*Connection nodes."
        ),
    )
    store_enabled: bool = False


class UpdateNodeSchema(BaseModel):
    id: str
    node_type: str | None = None
    display_name: str | None = None
    comment: str | None = Field(default=None, max_length=20480)
    position: PositionSchema | None = None
    subgraph_id: str | None = None
    inputs: dict[str, InputValueSchema | None] | None = Field(
        default=None,
        description=(
            "Only changed inputs; omitted keys are preserved and null entries remove values."
        ),
    )
    store_enabled: bool | None = None


class AddConnectionSchema(BaseModel):
    id: str | None = None
    source: str
    source_output: str
    target: str
    target_input: str
    subgraph_id: str | None = None


class GraphPatchSchema(BaseModel):
    add_nodes: list[AddNodeSchema] = Field(default_factory=list)
    update_nodes: list[UpdateNodeSchema] = Field(default_factory=list)
    delete_node_ids: list[str] = Field(default_factory=list)
    add_connections: list[AddConnectionSchema] = Field(default_factory=list)
    delete_connection_ids: list[str] = Field(default_factory=list)


def compute_graph_etag(nodes, edges, subgraphs) -> str:
    payload = {
        "nodes": sorted(
            [graph_nodes_dto.to_ui(node).model_dump(mode="json") for node in nodes],
            key=lambda item: item["id"],
        ),
        "edges": sorted(
            [graph_edges_dto.to_ui(edge).model_dump(mode="json") for edge in edges],
            key=lambda item: item["id"],
        ),
        "subgraphs": sorted(
            [subgraphs_dto.to_ui(item).model_dump(mode="json") for item in subgraphs],
            key=lambda item: item["id"],
        ),
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _canonical_input(value: InputValueSchema) -> dict[str, Any]:
    if value.kind == "constant":
        return {"__dvt_type": "const", "value": value.value}
    if value.kind == "expression":
        if not isinstance(value.value, str) or not value.value.strip():
            raise ValueError("Expression input requires a non-empty string value.")
        return {
            "__dvt_type": "expr",
            "value": value.value,
            "expression_kind": value.expression_kind,
        }
    if not value.connection_id:
        raise ValueError("connection_ref input requires connection_id.")
    return {"__dvt_type": "const", "value": value.connection_id}


def _ai_input(value: Any, *, accessible_connection_ids: set[str]) -> dict[str, Any]:
    parsed = parse_node_input_value(value)
    if parsed is None:
        return {"kind": "constant", "value": value}
    dumped = parsed.model_dump(by_alias=True, mode="json")
    if dumped["__dvt_type"] == "expr":
        return {
            "kind": "expression",
            "value": dumped["value"],
            "expression_kind": dumped["expression_kind"],
        }
    if dumped["__dvt_type"] == "link":
        return {
            "kind": "link",
            "source": dumped["node_id"],
            "source_output": dumped["output_name"],
        }
    raw_value = dumped.get("value")
    if isinstance(raw_value, str) and raw_value in accessible_connection_ids:
        return {"kind": "connection_ref", "connection_id": raw_value, "accessible": True}
    return {"kind": "constant", "value": raw_value}


def _input_names_with_type_suffixes(node_name: str, suffixes: tuple[str, ...]) -> set[str]:
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


def _connection_input_names(node_name: str) -> set[str]:
    return _input_names_with_type_suffixes(
        node_name,
        ("_CONNECTION", "_CONNECTION_ID"),
    )


def _connection_object_input_names(node_name: str) -> set[str]:
    return _input_names_with_type_suffixes(node_name, ("_CONNECTION",))


def _matches_constant_type(value: Any, declared_types: set[str]) -> bool:
    if "*" in declared_types or "OBJECT" in declared_types:
        return True
    checks = {
        "STRING": lambda item: isinstance(item, str),
        "COLUMN": lambda item: isinstance(item, str),
        "COLUMN_NAME": lambda item: isinstance(item, str),
        "BOOLEAN": lambda item: isinstance(item, bool),
        "INT": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "FLOAT": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
        "DICT": lambda item: isinstance(item, dict),
        "JSON": lambda _item: True,
        "DATETIME": lambda item: isinstance(item, str),
        "TIMEDELTA": lambda item: (
            isinstance(item, (str, int, float)) and not isinstance(item, bool)
        ),
        "SCHEMA": lambda item: isinstance(item, dict),
        "TABLE_SCHEMA": lambda item: isinstance(item, dict),
        # Variable ports carry a name -> variable payload mapping.  An empty
        # mapping is the normal persisted default for nodes without variables.
        "VARIABLE": lambda item: isinstance(item, dict),
        "PRIMITIVE": lambda item: isinstance(item, (str, int, float, bool)),
    }
    return any(checks[name](value) for name in declared_types if name in checks)


def _constant_validation_error(input_definition, value: Any) -> str | None:
    if value is None:
        return None if input_definition.optional else "Required constant value cannot be null."
    values = value if input_definition.is_list_type and isinstance(value, list) else [value]
    if input_definition.is_list_type and not isinstance(value, list):
        return "Input requires a list value."
    declared_types = {
        member.strip()
        for item in (
            input_definition.type
            if isinstance(input_definition.type, list)
            else [input_definition.type]
        )
        for member in str(item).upper().split(",")
    }
    for item in values:
        if not _matches_constant_type(item, declared_types):
            return f"Constant value is incompatible with {sorted(declared_types)}."
        if input_definition.options is not None and item not in input_definition.options:
            return "Constant value is not one of the allowed options."
        if isinstance(item, (int, float)) and not isinstance(item, bool):
            bounds_error = None
            if input_definition.min_value is not None and item < input_definition.min_value:
                bounds_error = f"Constant value is below minimum {input_definition.min_value}."
            elif input_definition.max_value is not None and item > input_definition.max_value:
                bounds_error = f"Constant value exceeds maximum {input_definition.max_value}."
            if bounds_error:
                return bounds_error
    return None


def _graph_constant_validation_error(
    input_definition,
    value: Any,
    *,
    node_id: str,
    input_name: str,
    incoming_inputs: set[tuple[str, str]],
    connection_input_names: set[str],
) -> str | None:
    # A graph edge is the effective value for its target input.  Persisted
    # constants (commonly a null placeholder) must not invalidate that input.
    if input_name in connection_input_names or (node_id, input_name) in incoming_inputs:
        return None
    return _constant_validation_error(input_definition, value)


def _read_table_mcp_configuration_errors(
    *,
    node_id: str,
    inputs: dict[str, Any],
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []

    partition_value = parse_node_input_value(inputs.get("partition_col"))
    partition_col = (
        partition_value.value
        if partition_value is not None and partition_value.dvt_type == "const"
        else None
    )
    quoted_partition = (
        isinstance(partition_col, str)
        and len(partition_col) >= 2
        and (
            (partition_col.startswith("`") and partition_col.endswith("`"))
            or (partition_col.startswith('"') and partition_col.endswith('"'))
            or (partition_col.startswith("[") and partition_col.endswith("]"))
        )
    )
    if not isinstance(partition_col, str) or not partition_col.strip():
        errors.append(
            {
                "code": "REQUIRED_INPUT_MISSING",
                "node_id": node_id,
                "input": "partition_col",
                "message": (
                    "ReadTableFromDBV3 requires an explicit partition_col from the table catalog."
                ),
            }
        )
    elif quoted_partition:
        errors.append(
            {
                "code": "INVALID_CONSTANT",
                "node_id": node_id,
                "input": "partition_col",
                "message": "Use the raw catalog column name without SQL quotes or backticks.",
            }
        )

    columns_value = parse_node_input_value(inputs.get("columns"))
    columns = (
        columns_value.value
        if columns_value is not None and columns_value.dvt_type == "const"
        else None
    )
    if not isinstance(columns, list) or not columns or not all(
        isinstance(column, str) and column.strip() for column in columns
    ):
        errors.append(
            {
                "code": "REQUIRED_INPUT_MISSING",
                "node_id": node_id,
                "input": "columns",
                "message": (
                    "ReadTableFromDBV3 requires an explicit non-empty columns list. "
                    "Pass every column returned by get_database_table to select all columns."
                ),
            }
        )
    return errors


def _expression_validation_error(
    input_definition,
    *,
    expression: str,
    expression_kind: str,
    project_variable_names: set[str],
) -> str | None:
    try:
        policy = resolve_expression_policy(input_definition.expression_policy)
        environment = build_environment(policy)
        if expression_kind == "single":
            environment.compile_expression(expression, undefined_to_none=False)
        elif expression_kind == "template":
            ensure_template_syntax_allowed(expression, policy)
            environment.from_string(expression)
        else:
            return "Unsupported expression kind."
    except (TypeError, ValueError, SyntaxError, TemplateError) as exc:
        return f"Expression is invalid: {exc}"
    referenced_project_variables = {
        dot_name or bracket_name
        for dot_name, bracket_name in _PROJECT_VARIABLE_RE.findall(expression)
    }
    missing = sorted(referenced_project_variables - project_variable_names)
    if missing:
        return f"Project variables do not exist: {missing}."
    return None


def _is_valid_dvt_service_reference(
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


def _connection_object_requires_edge(
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
    if _is_valid_dvt_service_reference(
        raw,
        project_id=project_id,
        node_id=node_id,
        input_name=input_name,
    ) and raw == existing_dvt_reference:
        return False
    return raw is not None or not optional


def analyze_graph_connection_dependencies(
    nodes,
    *,
    project_id: str,
) -> tuple[set[str], list[dict[str, str]]]:
    connection_ids: set[str] = set()
    unresolved: list[dict[str, str]] = []
    for node in nodes:
        names = _connection_input_names(node.name)
        object_names = _connection_object_input_names(node.name)
        for name in names:
            if name not in (node.input_values or {}):
                continue
            value = (node.input_values or {}).get(name)
            try:
                parsed = parse_node_input_value(value)
            except (TypeError, ValueError):
                parsed = None
            if parsed is None:
                if value is not None:
                    unresolved.append({"node_id": node.ui_id, "input_name": name})
                continue
            dumped = parsed.model_dump(by_alias=True, mode="json")
            raw = dumped.get("value")
            if name in object_names:
                if _is_valid_dvt_service_reference(
                    raw,
                    project_id=project_id,
                    node_id=node.ui_id,
                    input_name=name,
                ):
                    continue
                if raw is not None or dumped.get("__dvt_type") != "const":
                    unresolved.append({"node_id": node.ui_id, "input_name": name})
                continue
            if dumped.get("__dvt_type") != "const":
                unresolved.append({"node_id": node.ui_id, "input_name": name})
            elif isinstance(raw, str) and raw:
                connection_ids.add(raw)
            elif _is_valid_dvt_service_reference(
                raw,
                project_id=project_id,
                node_id=node.ui_id,
                input_name=name,
            ):
                continue
            elif raw is not None:
                unresolved.append({"node_id": node.ui_id, "input_name": name})
    return connection_ids, unresolved


def extract_graph_connection_ids(nodes, *, project_id: str) -> set[str]:
    connection_ids, _ = analyze_graph_connection_dependencies(
        nodes,
        project_id=project_id,
    )
    return connection_ids


async def get_project_graph(
    *,
    session,
    principal: MCPPrincipal,
    project_id: str,
    cursor: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    project = await get_accessible_project(session, principal, project_id)
    nodes, edges, subgraphs = await graph_crud.get_graph_by(
        session,
        organization_id=project.organization_id,
        owner_user_id=project.user_id,
        project_id=project.id,
    )
    nodes = list(nodes)
    edges = list(edges)
    subgraphs = list(subgraphs)
    graph_etag = compute_graph_etag(nodes, edges, subgraphs)
    offset = decode_cursor(cursor)
    limit = max(1, min(limit, 200))
    ordered_nodes = sorted(nodes, key=lambda item: item.ui_id)
    page_nodes = ordered_nodes[offset : offset + limit]
    page_ids = {node.ui_id for node in page_nodes}
    connection_ids = extract_graph_connection_ids(nodes, project_id=project.id)
    accessible_connections: set[str] = set()
    for connection_id in connection_ids:
        try:
            await get_accessible_connection(principal, connection_id)
            accessible_connections.add(connection_id)
        except AIMCPHTTPError:
            pass
    node_payloads = []
    for node in page_nodes:
        connection_inputs = _connection_input_names(node.name)
        inputs = {}
        for name, value in (node.input_values or {}).items():
            if name in connection_inputs:
                parsed = parse_node_input_value(value)
                raw = None if parsed is None else parsed.model_dump(by_alias=True).get("value")
                if isinstance(raw, dict) and raw.get("type") == "dvt_service_files":
                    connection_id = raw.get("id")
                    inputs[name] = {
                        "kind": "connection_ref",
                        "connection_id": connection_id if isinstance(connection_id, str) else None,
                        "accessible": _is_valid_dvt_service_reference(
                            raw,
                            project_id=project.id,
                            node_id=node.ui_id,
                            input_name=name,
                        ),
                    }
                    continue
                if isinstance(raw, str) and raw not in accessible_connections:
                    inputs[name] = {
                        "kind": "connection_ref",
                        "connection_id": raw,
                        "accessible": False,
                    }
                    continue
            inputs[name] = _ai_input(value, accessible_connection_ids=accessible_connections)
        node_payloads.append(
            {
                "id": node.ui_id,
                "node_type": node.name,
                "ui_type": node.type,
                "display_name": node.display_name,
                "comment": node.comment,
                "position": {"x": node.position_x, "y": node.position_y},
                "subgraph_id": node.subgraph_id,
                "store_enabled": node.store_enabled,
                "inputs": inputs,
            }
        )
    page_edges = [edge for edge in edges if edge.target in page_ids]
    return {
        "project_id": project.id,
        "graph_revision": project.graph_revision,
        "graph_etag": graph_etag,
        "nodes": node_payloads,
        "connections": [
            {
                "id": edge.ui_id,
                "source": edge.source,
                "source_output": (edge.source_handle or "").removeprefix("output-"),
                "target": edge.target,
                "target_input": (edge.target_handle or "").removeprefix("input-"),
                "subgraph_id": edge.subgraph_id,
            }
            for edge in sorted(page_edges, key=lambda item: item.ui_id)
        ],
        "subgraphs": [subgraphs_dto.to_ui(item).model_dump(mode="json") for item in subgraphs],
        "next_cursor": encode_cursor(offset + len(page_nodes), len(ordered_nodes)),
    }


def _next_position(
    *,
    node_id: str,
    layers: dict[str, int],
    occupied: list[tuple[float, float, str | None]],
    subgraph_id: str | None,
    node_subgraphs: dict[str, str | None],
) -> tuple[float, float]:
    layer = layers.get(node_id, 0)
    sibling_layers = [
        layers.get(other_id, 0)
        for other_id, other_subgraph_id in node_subgraphs.items()
        if other_subgraph_id == subgraph_id
    ]
    relative_layer = layer - min(sibling_layers, default=0)
    subgraph_members = [
        (x, y) for x, y, occupied_subgraph_id in occupied if occupied_subgraph_id == subgraph_id
    ]
    base_x = min((pos[0] for pos in subgraph_members), default=0.0)
    x = base_x + relative_layer * X_STEP
    y = min((pos[1] for pos in subgraph_members), default=0.0)
    while any(abs(x - ox) < 300 and abs(y - oy) < 160 for ox, oy in subgraph_members):
        y += Y_STEP
    return x, y


def _topological_layers(node_ids: set[str], edges: list[dict[str, Any]]) -> dict[str, int]:
    incoming = dict.fromkeys(node_ids, 0)
    outgoing: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        if edge["source"] in node_ids and edge["target"] in node_ids:
            incoming[edge["target"]] += 1
            outgoing[edge["source"]].append(edge["target"])
    queue = deque(sorted(node_id for node_id, count in incoming.items() if count == 0))
    layers = dict.fromkeys(queue, 0)
    while queue:
        source = queue.popleft()
        for target in sorted(outgoing[source]):
            layers[target] = max(layers.get(target, 0), layers[source] + 1)
            incoming[target] -= 1
            if incoming[target] == 0:
                queue.append(target)
    return layers


async def _prepare_patch(
    *,
    session,
    principal: MCPPrincipal,
    project,
    patch: GraphPatchSchema,
) -> tuple[
    GraphOperationsAggregated, list[GraphNodeRecord], list[GraphEdgeRecord], list, list[dict]
]:
    existing_nodes, existing_edges, subgraphs = await graph_crud.get_graph_by(
        session,
        organization_id=project.organization_id,
        owner_user_id=project.user_id,
        project_id=project.id,
    )
    existing_nodes = list(existing_nodes)
    existing_edges = list(existing_edges)
    subgraphs = list(subgraphs)
    node_map = {
        item.ui_id: graph_nodes_dto.to_ui(item).model_dump(mode="json") for item in existing_nodes
    }
    edge_map = {
        item.ui_id: graph_edges_dto.to_ui(item).model_dump(mode="json") for item in existing_edges
    }
    subgraph_ids = {item.ui_id for item in subgraphs}
    existing_dvt_references: dict[tuple[str, str], Any] = {}
    for existing_node in existing_nodes:
        for input_name in _connection_input_names(existing_node.name):
            parsed = parse_node_input_value((existing_node.input_values or {}).get(input_name))
            raw = None if parsed is None else parsed.model_dump(by_alias=True).get("value")
            if _is_valid_dvt_service_reference(
                raw,
                project_id=project.id,
                node_id=existing_node.ui_id,
                input_name=input_name,
            ):
                existing_dvt_references[(existing_node.ui_id, input_name)] = raw
    warnings: list[dict] = []
    errors: list[dict] = []

    delete_node_ids = set(patch.delete_node_ids)
    unknown_deletes = sorted(delete_node_ids - node_map.keys())
    if unknown_deletes:
        errors.append({"code": "UNKNOWN_NODE", "node_ids": unknown_deletes})
    for node_id in delete_node_ids:
        node_map.pop(node_id, None)

    touched_code_nodes: set[str] = set()
    for item in patch.update_nodes:
        node = node_map.get(item.id)
        if node is None:
            errors.append({"code": "UNKNOWN_NODE", "node_id": item.id})
            continue
        fields = item.model_fields_set
        if "node_type" in fields and item.node_type is not None:
            node["data"]["name"] = item.node_type
        if "display_name" in fields:
            node["data"]["displayName"] = item.display_name or node["data"]["name"]
        if "comment" in fields:
            node["data"]["comment"] = item.comment
        if "position" in fields and item.position is not None:
            node["position"] = item.position.model_dump()
        if "subgraph_id" in fields:
            if item.subgraph_id is not None and item.subgraph_id not in subgraph_ids:
                errors.append({"code": "UNKNOWN_SUBGRAPH", "subgraph_id": item.subgraph_id})
            node["subgraphId"] = item.subgraph_id
        if "store_enabled" in fields and item.store_enabled is not None:
            node["data"]["storeEnabled"] = item.store_enabled
        if "inputs" in fields and item.inputs is not None:
            for name, value in item.inputs.items():
                if value is None:
                    node["data"]["inputValues"].pop(name, None)
                else:
                    try:
                        node["data"]["inputValues"][name] = _canonical_input(value)
                    except ValueError as exc:
                        errors.append(
                            {"code": "INVALID_INPUT", "node_id": item.id, "message": str(exc)}
                        )
        if node["data"]["name"] in GENERIC_CODE_NODES:
            touched_code_nodes.add(item.id)

    for item in patch.add_nodes:
        if item.id in node_map:
            errors.append({"code": "DUPLICATE_NODE_ID", "node_id": item.id})
            continue
        if item.subgraph_id is not None and item.subgraph_id not in subgraph_ids:
            errors.append({"code": "UNKNOWN_SUBGRAPH", "subgraph_id": item.subgraph_id})
        inputs: dict[str, Any] = {}
        for name, value in item.inputs.items():
            if value is None:
                continue
            try:
                inputs[name] = _canonical_input(value)
            except ValueError as exc:
                errors.append({"code": "INVALID_INPUT", "node_id": item.id, "message": str(exc)})
        node_map[item.id] = {
            "id": item.id,
            "type": "custom",
            "subgraphId": item.subgraph_id,
            "position": item.position.model_dump() if item.position else None,
            "selected": False,
            "data": {
                "name": item.node_type,
                "displayName": item.display_name or item.node_type,
                "comment": item.comment,
                "inputValues": inputs,
                "storeEnabled": item.store_enabled,
                "showSignalIo": False,
                "showVariablesIo": False,
            },
        }
        if item.node_type in GENERIC_CODE_NODES:
            touched_code_nodes.add(item.id)

    implicit_edge_deletes = {
        edge_id
        for edge_id, edge in edge_map.items()
        if edge["source"] in delete_node_ids or edge["target"] in delete_node_ids
    }
    delete_edge_ids = set(patch.delete_connection_ids) | implicit_edge_deletes
    unknown_edge_deletes = sorted(set(patch.delete_connection_ids) - edge_map.keys())
    if unknown_edge_deletes:
        errors.append({"code": "UNKNOWN_CONNECTION", "connection_ids": unknown_edge_deletes})
    for edge_id in delete_edge_ids:
        edge_map.pop(edge_id, None)

    for item in patch.add_connections:
        edge_id = item.id or str(uuid4())
        if edge_id in edge_map:
            errors.append({"code": "DUPLICATE_CONNECTION_ID", "connection_id": edge_id})
            continue
        if item.source not in node_map or item.target not in node_map:
            errors.append({"code": "UNKNOWN_CONNECTION_NODE", "connection_id": edge_id})
            continue
        subgraph_id = item.subgraph_id
        if subgraph_id is None and node_map[item.source].get("subgraphId") == node_map[
            item.target
        ].get("subgraphId"):
            subgraph_id = node_map[item.source].get("subgraphId")
        if subgraph_id is not None and subgraph_id not in subgraph_ids:
            errors.append({"code": "UNKNOWN_SUBGRAPH", "subgraph_id": subgraph_id})
        edge_map[edge_id] = {
            "id": edge_id,
            "type": "custom",
            "subgraphId": subgraph_id,
            "source": item.source,
            "sourceHandle": f"output-{item.source_output}",
            "target": item.target,
            "targetHandle": f"input-{item.target_input}",
        }

    final_edge_dicts = list(edge_map.values())
    layers = _topological_layers(set(node_map), final_edge_dicts)
    existing_ids = {item.ui_id for item in existing_nodes} - delete_node_ids
    explicit_position_ids = {
        item.id
        for item in patch.update_nodes
        if "position" in item.model_fields_set and item.position is not None
    }
    dynamic_position_ids = {item.id for item in patch.add_nodes} | explicit_position_ids
    occupied = [
        (node["position"]["x"], node["position"]["y"], node.get("subgraphId"))
        for node_id, node in node_map.items()
        if node_id in existing_ids
        and node_id not in explicit_position_ids
        and node.get("position") is not None
    ]
    node_subgraphs = {node_id: node.get("subgraphId") for node_id, node in node_map.items()}
    for node_id in sorted(dynamic_position_ids):
        if node_id not in node_map:
            continue
        node = node_map[node_id]
        position = node.get("position")
        overlaps = position is not None and any(
            abs(position["x"] - x) < 300 and abs(position["y"] - y) < 160
            for x, y, occupied_subgraph_id in occupied
            if occupied_subgraph_id == node.get("subgraphId")
        )
        if position is None or overlaps:
            x, y = _next_position(
                node_id=node_id,
                layers=layers,
                occupied=occupied,
                subgraph_id=node.get("subgraphId"),
                node_subgraphs=node_subgraphs,
            )
            node["position"] = {"x": x, "y": y}
            if overlaps:
                warnings.append({"code": "POSITION_ADJUSTED", "node_id": node_id})
        occupied.append((node["position"]["x"], node["position"]["y"], node.get("subgraphId")))

    available = await _available_definitions(session, "en")
    project_variable_names = set((project.variables or {}).keys())
    incoming_inputs = {
        (edge["target"], (edge.get("targetHandle") or "").removeprefix("input-"))
        for edge in final_edge_dicts
    }
    for node_id, node in node_map.items():
        node_name = node["data"]["name"]
        definition = available.get(node_name)
        if definition is None:
            errors.append(
                {"code": "NODE_NOT_AVAILABLE", "node_id": node_id, "node_type": node_name}
            )
            continue
        inputs = node["data"].get("inputValues") or {}
        connection_input_names = _connection_input_names(node_name)
        connection_object_input_names = _connection_object_input_names(node_name)
        unknown_inputs = sorted(set(inputs) - set(definition.input_definitions))
        if unknown_inputs:
            errors.append({"code": "UNKNOWN_INPUT", "node_id": node_id, "inputs": unknown_inputs})
        for input_name, input_definition in definition.input_definitions.items():
            has_default = input_definition.default is not None
            if (
                not input_definition.optional
                and not has_default
                and input_name not in inputs
                and (node_id, input_name) not in incoming_inputs
                and input_name not in connection_object_input_names
            ):
                errors.append(
                    {"code": "REQUIRED_INPUT_MISSING", "node_id": node_id, "input": input_name}
                )
            value = inputs.get(input_name)
            parsed = parse_node_input_value(value)
            if (
                parsed is not None
                and parsed.dvt_type == "expr"
                and not input_definition.allow_expressions
            ):
                errors.append(
                    {"code": "EXPRESSION_NOT_ALLOWED", "node_id": node_id, "input": input_name}
                )
            elif parsed is not None and parsed.dvt_type == "expr":
                expression_error = _expression_validation_error(
                    input_definition,
                    expression=parsed.value,
                    expression_kind=parsed.expression_kind,
                    project_variable_names=project_variable_names,
                )
                if expression_error:
                    errors.append(
                        {
                            "code": "INVALID_EXPRESSION",
                            "node_id": node_id,
                            "input": input_name,
                            "message": expression_error,
                        }
                    )
            elif (
                parsed is not None
                and parsed.dvt_type == "const"
            ):
                constant_error = _graph_constant_validation_error(
                    input_definition,
                    parsed.value,
                    node_id=node_id,
                    input_name=input_name,
                    incoming_inputs=incoming_inputs,
                    connection_input_names=connection_input_names,
                )
                if constant_error:
                    errors.append(
                        {
                            "code": "INVALID_CONSTANT",
                            "node_id": node_id,
                            "input": input_name,
                            "message": constant_error,
                        }
                    )
        for input_name in connection_input_names:
            input_definition = definition.input_definitions[input_name]
            value = inputs.get(input_name)
            parsed = parse_node_input_value(value)
            dumped = None if parsed is None else parsed.model_dump(by_alias=True)
            raw = None if dumped is None else dumped.get("value")
            if input_name in connection_object_input_names:
                if _connection_object_requires_edge(
                    raw,
                    optional=input_definition.optional,
                    has_incoming_edge=(node_id, input_name) in incoming_inputs,
                    project_id=project.id,
                    node_id=node_id,
                    input_name=input_name,
                    existing_dvt_reference=existing_dvt_references.get((node_id, input_name)),
                ):
                    errors.append(
                        {
                            "code": "CONNECTION_NODE_REQUIRED",
                            "node_id": node_id,
                            "input": input_name,
                            "message": (
                                "Connection object inputs require an incoming edge from the "
                                "matching GetExist*Connection.connection output. Put the scoped "
                                "connection ID only in that connection node's connection_id input."
                            ),
                        }
                    )
                continue
            if dumped is None or raw is None:
                continue
            if dumped.get("__dvt_type") != "const":
                errors.append(
                    {
                        "code": "UNRESOLVED_CONNECTION_REFERENCE",
                        "node_id": node_id,
                        "input": input_name,
                    }
                )
            elif isinstance(raw, str):
                try:
                    await get_accessible_connection(principal, raw)
                except AIMCPHTTPError:
                    errors.append(
                        {
                            "code": "CONNECTION_NOT_FOUND_OR_DENIED",
                            "node_id": node_id,
                            "input": input_name,
                        }
                    )
            elif _is_valid_dvt_service_reference(
                raw,
                project_id=project.id,
                node_id=node_id,
                input_name=input_name,
            ) and raw == existing_dvt_references.get((node_id, input_name)):
                continue
            else:
                errors.append(
                    {
                        "code": "CONNECTION_NOT_FOUND_OR_DENIED",
                        "node_id": node_id,
                        "input": input_name,
                    }
                )

        if node_name == "ReadTableFromDBV3":
            errors.extend(
                _read_table_mcp_configuration_errors(node_id=node_id, inputs=inputs)
            )

    for node_id in touched_code_nodes:
        comment = (node_map.get(node_id, {}).get("data", {}).get("comment") or "").strip()
        if not comment:
            errors.append({"code": "GENERIC_CODE_COMMENT_REQUIRED", "node_id": node_id})

    generic_node_ids = sorted(
        node_id for node_id, node in node_map.items() if node["data"]["name"] in GENERIC_CODE_NODES
    )
    for node_id in generic_node_ids:
        warnings.append({"code": "GENERIC_CODE_NODE", "severity": "high", "node_id": node_id})
    generic_count = len(generic_node_ids)
    if generic_count and generic_count * 2 >= len(node_map):
        warnings.append({"code": "GENERIC_CODE_HEAVY_GRAPH", "severity": "high"})
    for node_id, node in node_map.items():
        if not (node["data"].get("displayName") or "").strip():
            warnings.append({"code": "MISSING_DISPLAY_NAME", "node_id": node_id})
        if not (node["data"].get("comment") or "").strip():
            warnings.append({"code": "MISSING_COMMENT", "node_id": node_id})
    positioned = sorted(
        (
            node_id,
            node["position"]["x"],
            node["position"]["y"],
            node.get("subgraphId"),
        )
        for node_id, node in node_map.items()
    )
    for index, (node_id, x, y, subgraph_id) in enumerate(positioned):
        for other_id, other_x, other_y, other_subgraph_id in positioned[index + 1 :]:
            if (
                subgraph_id == other_subgraph_id
                and abs(x - other_x) < 300
                and abs(y - other_y) < 160
            ):
                warnings.append({"code": "NODE_OVERLAP", "node_ids": [node_id, other_id]})

    final_nodes = [
        graph_nodes_dto.to_persistent(
            GraphNodeUISchema.model_validate(node),
            project_id=project.id,
            user_id=project.user_id,
            organization_id=project.organization_id,
        )
        for node in node_map.values()
    ]
    final_edges = [
        graph_edges_dto.to_persistent(
            GraphEdgeUISchema.model_validate(edge),
            project_id=project.id,
            user_id=project.user_id,
            organization_id=project.organization_id,
        )
        for edge in final_edge_dicts
    ]
    if final_nodes:
        validation = validate_pipeline(build_pipeline_from_graph(final_nodes, final_edges))
        if not validation.is_valid:
            errors.append(
                {"code": "PIPELINE_INVALID", "validation": validation.model_dump(mode="json")}
            )
    else:
        errors.append({"code": "PIPELINE_EMPTY"})

    if errors:
        raise AIMCPHTTPError(
            422,
            "GRAPH_VALIDATION_FAILED",
            "Graph changes did not pass validation.",
            details={"errors": errors, "warnings": warnings},
        )

    create_ids = {item.id for item in patch.add_nodes}
    update_ids = {item.id for item in patch.update_nodes}
    payload = GraphOperationsAggregated(
        nodes_to_delete=[{"id": node_id} for node_id in sorted(delete_node_ids)],
        nodes_to_create=[
            GraphNodeUISchema.model_validate(node_map[node_id])
            for node_id in sorted(create_ids)
            if node_id in node_map
        ],
        nodes_to_update=[
            node_map[node_id] for node_id in sorted(update_ids) if node_id in node_map
        ],
        edges_to_delete=[{"id": edge_id} for edge_id in sorted(delete_edge_ids)],
        edges_to_create=[
            GraphEdgeUISchema.model_validate(edge)
            for edge_id, edge in edge_map.items()
            if edge_id not in {item.ui_id for item in existing_edges}
        ],
    )
    return payload, final_nodes, final_edges, subgraphs, warnings


async def validate_graph_changes(
    *,
    session,
    principal: MCPPrincipal,
    project_id: str,
    expected_graph_revision: int,
    expected_graph_etag: str,
    patch: dict[str, Any],
) -> dict[str, Any]:
    project = await get_accessible_project(session, principal, project_id)
    current_nodes, current_edges, current_subgraphs = await graph_crud.get_graph_by(
        session,
        organization_id=project.organization_id,
        owner_user_id=project.user_id,
        project_id=project.id,
    )
    current_etag = compute_graph_etag(current_nodes, current_edges, current_subgraphs)
    if project.graph_revision != expected_graph_revision:
        raise AIMCPHTTPError(409, "GRAPH_REVISION_CONFLICT", "Graph revision has changed.")
    if current_etag != expected_graph_etag:
        raise AIMCPHTTPError(409, "GRAPH_ETAG_CONFLICT", "Graph content has changed.")
    _, final_nodes, final_edges, subgraphs, warnings = await _prepare_patch(
        session=session,
        principal=principal,
        project=project,
        patch=GraphPatchSchema.model_validate(patch),
    )
    return {
        "valid": True,
        "warnings": warnings,
        "preview_graph_etag": compute_graph_etag(final_nodes, final_edges, subgraphs),
    }


async def apply_graph_changes(
    *,
    session,
    principal: MCPPrincipal,
    project_id: str,
    expected_graph_revision: int,
    expected_graph_etag: str,
    patch: dict[str, Any],
) -> dict[str, Any]:
    project = await get_accessible_project(
        session,
        principal,
        project_id,
        for_update=True,
    )
    current_nodes, current_edges, current_subgraphs = await graph_crud.get_graph_by(
        session,
        organization_id=project.organization_id,
        owner_user_id=project.user_id,
        project_id=project.id,
    )
    current_etag = compute_graph_etag(current_nodes, current_edges, current_subgraphs)
    if project.graph_revision != expected_graph_revision:
        raise AIMCPHTTPError(409, "GRAPH_REVISION_CONFLICT", "Graph revision has changed.")
    if current_etag != expected_graph_etag:
        raise AIMCPHTTPError(409, "GRAPH_ETAG_CONFLICT", "Graph content has changed.")
    payload, _, _, _, warnings = await _prepare_patch(
        session=session,
        principal=principal,
        project=project,
        patch=GraphPatchSchema.model_validate(patch),
    )
    result = await ApplyGraphOperationsUseCase().execute(
        project_id=project_id,
        payload=payload,
        user=principal.user,
        session=session,
        source=TaskSource.MCP,
    )
    refreshed = await get_accessible_project(session, principal, project_id)
    nodes, edges, subgraphs = await graph_crud.get_graph_by(
        session,
        organization_id=refreshed.organization_id,
        owner_user_id=refreshed.user_id,
        project_id=refreshed.id,
    )
    return {
        **result.model_dump(mode="json"),
        "graph_revision": refreshed.graph_revision,
        "graph_etag": compute_graph_etag(nodes, edges, subgraphs),
        "warnings": warnings,
    }
