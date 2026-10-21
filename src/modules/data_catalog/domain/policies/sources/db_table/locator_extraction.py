"""Чистый проход по снэпшоту графа: какие ноды и с каким connection'ом адресуют таблицы БД."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from ....catalog_values import ProjectionDiagnostic
from ....graph import GraphInputValue, GraphNode, ProjectGraphSnapshot
from ....types import DiagnosticReason, LinkDirection, LocatorKind
from .node_locators import (
    CONNECTION_SOURCE_NODES,
    NODE_LOCATOR_SPECS,
    READ_VARIABLES_DEFAULT_MODE,
    READ_VARIABLES_SQL_MODE,
    NodeLocatorSpec,
)


@dataclass(frozen=True, slots=True)
class LocatorCandidate:
    """Нода с статически известным connection'ом и ещё не вычисленными локаторными входами."""

    node_id: str
    node_name: str
    direction: LinkDirection
    kind: LocatorKind
    connection_id: str
    spec: NodeLocatorSpec
    inputs: Mapping[str, GraphInputValue] = field(default_factory=dict)
    dataframe_input_names: frozenset[str] = frozenset()


def extract_locator_candidates(
    snapshot: ProjectGraphSnapshot,
) -> tuple[list[LocatorCandidate], list[ProjectionDiagnostic]]:
    nodes_by_id = {node.ui_id: node for node in snapshot.nodes}
    incoming: dict[tuple[str, str], str] = {}
    connected_inputs: dict[str, set[str]] = {}
    for edge in snapshot.edges:
        input_name = edge.target_input
        if input_name is None:
            continue
        incoming[(edge.target, input_name)] = edge.source
        connected_inputs.setdefault(edge.target, set()).add(input_name)

    candidates: list[LocatorCandidate] = []
    diagnostics: list[ProjectionDiagnostic] = []

    for node in snapshot.nodes:
        spec = NODE_LOCATOR_SPECS.get(node.name)
        if spec is None:
            continue

        connection_id, diagnostic = _resolve_static_connection(
            node=node,
            spec=spec,
            incoming=incoming,
            nodes_by_id=nodes_by_id,
        )
        if diagnostic is not None:
            diagnostics.append(diagnostic)
            continue
        assert connection_id is not None

        inputs, diagnostic = _collect_locator_inputs(node=node, spec=spec)
        if diagnostic is not None:
            diagnostics.append(diagnostic)
            continue

        dataframe_inputs = frozenset(
            name
            for name in connected_inputs.get(node.ui_id, set())
            if name != spec.connection_input
        )
        candidates.append(
            LocatorCandidate(
                node_id=node.ui_id,
                node_name=node.name,
                direction=spec.direction,
                kind=spec.kind,
                connection_id=connection_id,
                spec=spec,
                inputs=inputs,
                dataframe_input_names=dataframe_inputs,
            )
        )

    return candidates, diagnostics


def _resolve_static_connection(
    *,
    node: GraphNode,
    spec: NodeLocatorSpec,
    incoming: Mapping[tuple[str, str], str],
    nodes_by_id: Mapping[str, GraphNode],
) -> tuple[str | None, ProjectionDiagnostic | None]:
    source_id = incoming.get((node.ui_id, spec.connection_input))
    if source_id is None:
        return None, _diag(node, DiagnosticReason.CONNECTION_EDGE_MISSING)

    source = nodes_by_id.get(source_id)
    if source is None:
        return None, _diag(node, DiagnosticReason.CONNECTION_EDGE_MISSING, f"source node {source_id} is absent")

    id_input = CONNECTION_SOURCE_NODES.get(source.name)
    if id_input is None:
        return None, _diag(node, DiagnosticReason.CONNECTION_NOT_STATIC, f"connection comes from {source.name}")

    value = source.inputs.get(id_input)
    if value is None or value.kind != "const":
        return None, _diag(node, DiagnosticReason.CONNECTION_NOT_STATIC, f"{source.name}.{id_input} is not a constant")

    connection_id = value.value
    if not isinstance(connection_id, str) or not connection_id.strip():
        return None, _diag(node, DiagnosticReason.CONNECTION_NOT_STATIC, f"{source.name}.{id_input} is empty")
    return connection_id.strip(), None


def _collect_locator_inputs(
    *,
    node: GraphNode,
    spec: NodeLocatorSpec,
) -> tuple[dict[str, GraphInputValue], ProjectionDiagnostic | None]:
    if spec.kind is LocatorKind.EXPLICIT:
        required = (spec.table_input,)
        optional = (spec.schema_input, spec.database_input, spec.columns_input)
    elif spec.kind is LocatorKind.SQL:
        required = (spec.sql_input,)
        optional = ()
    else:
        mode_value = node.inputs.get(spec.mode_input)
        mode = READ_VARIABLES_DEFAULT_MODE
        if mode_value is not None:
            if mode_value.kind != "const":
                return {}, _diag(node, DiagnosticReason.LINK_INPUT_UNSUPPORTED, f"{spec.mode_input} is not a constant")
            mode = str(mode_value.value or READ_VARIABLES_DEFAULT_MODE)
        if mode == READ_VARIABLES_SQL_MODE:
            required = (spec.sql_input,)
        else:
            required = (spec.manual_variables_input,)
        optional = (spec.mode_input,)

    collected: dict[str, GraphInputValue] = {}
    for name in required:
        value = node.inputs.get(name)
        if value is None or (value.kind == "const" and _is_blank(value.value)):
            return {}, _diag(node, DiagnosticReason.LOCATOR_INPUT_MISSING, name)
        if value.kind == "link":
            return {}, _diag(node, DiagnosticReason.LINK_INPUT_UNSUPPORTED, name)
        collected[name] = value
    for name in optional:
        value = node.inputs.get(name)
        if value is None:
            continue
        if value.kind == "link":
            return {}, _diag(node, DiagnosticReason.LINK_INPUT_UNSUPPORTED, name)
        collected[name] = value
    return collected, None


def _is_blank(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (dict, list, tuple, set)):
        return len(value) == 0
    return False


def _diag(node: GraphNode, reason: DiagnosticReason, detail: str | None = None) -> ProjectionDiagnostic:
    return ProjectionDiagnostic(node_id=node.ui_id, node_name=node.name, reason=reason, detail=detail)
