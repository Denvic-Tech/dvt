"""Статический проход по DataFrame-портам графа: топология, применение правил, финализация."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from ...catalog_values import ProjectionDiagnostic
from ...gateways import ColumnRulePlanner
from ...graph import GraphNode, ProjectGraphSnapshot
from ...lineage import (
    INPUT_ROLE,
    OUTPUT_ROLE,
    ColumnLineage,
    LineageRef,
    NodePortTypes,
    PortColumns,
    PortLineage,
    ProjectLineage,
)
from ...types import MAX_COLUMNS_PER_PORT, DiagnosticReason, LineageOp, PortStatus
from .builtin_rules import NON_STATIC_SOURCE_NODES
from .rules import LineageRuleRegistry, RuleContext, details, pass_column

_INTERNAL_PREFIX = "__dvt"

PortTypeLookup = Callable[[str], NodePortTypes | None]


@dataclass(slots=True)
class _Topology:
    nodes: dict[str, GraphNode]
    types: dict[str, NodePortTypes]
    incoming: dict[tuple[str, str], tuple[str, str]] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)
    cyclic: list[str] = field(default_factory=list)


def derive_project_lineage(
    snapshot: ProjectGraphSnapshot,
    *,
    port_types: PortTypeLookup,
    rules: LineageRuleRegistry,
    seeds: Mapping[str, Mapping[str, PortColumns]],
    planner: ColumnRulePlanner | None = None,
    max_columns_per_port: int = MAX_COLUMNS_PER_PORT,
) -> tuple[ProjectLineage, list[ProjectionDiagnostic]]:
    diagnostics: list[ProjectionDiagnostic] = []
    topology = _build_topology(snapshot, port_types, seeds, diagnostics)

    ports: dict[tuple[str, str], PortLineage] = {}
    origins: dict[str, LineageRef] = {}
    truncated = False

    for node_id in topology.order:
        node = topology.nodes[node_id]
        types = topology.types[node_id]
        inputs = _collect_inputs(node_id, types, topology, ports)

        if node_id in seeds:
            outputs: Mapping[str, PortColumns] = seeds[node_id]
        elif node.name in NON_STATIC_SOURCE_NODES:
            outputs = {
                name: PortColumns.unresolved(
                    DiagnosticReason.LINEAGE_SOURCE_NOT_STATIC, f"{node.name} has no static schema"
                )
                for name in types.dataframe_outputs
            }
        elif types.dataframe_outputs:
            rule = rules.get(node.name)
            if rule is None:
                diagnostics.append(_diag(node, DiagnosticReason.LINEAGE_RULE_MISSING))
                outputs = {
                    name: PortColumns.unresolved(DiagnosticReason.LINEAGE_RULE_MISSING, f"no lineage rule for {node.name}")
                    for name in types.dataframe_outputs
                }
            else:
                outputs = rule(RuleContext(node=node, inputs=inputs, port_types=types, planner=planner))
        else:
            outputs = {}

        for port_name in types.dataframe_outputs:
            result = outputs.get(port_name) or PortColumns.unresolved(
                DiagnosticReason.LINEAGE_RULE_MISSING, f"rule produced nothing for port {port_name}"
            )
            finalized, port_truncated = _finalize(
                node, port_name, OUTPUT_ROLE, result, origins, diagnostics, max_columns_per_port
            )
            truncated = truncated or port_truncated
            ports[(node_id, port_name)] = finalized

        if not types.dataframe_outputs:
            # Приёмник: снимок входа показывает, что именно записывается, и даёт dependents писателям.
            for input_name in sorted(types.dataframe_inputs):
                upstream = inputs.get(input_name)
                if upstream is None:
                    continue
                snapshot_port = PortColumns(
                    columns=tuple(pass_column(upstream, column, "lineage.pass.sink") for column in upstream.columns),
                    status=upstream.status,
                    reason=upstream.reason,
                    detail=upstream.detail,
                )
                finalized, port_truncated = _finalize(
                    node, input_name, INPUT_ROLE, snapshot_port, origins, diagnostics, max_columns_per_port
                )
                truncated = truncated or port_truncated
                ports[(node_id, input_name)] = finalized

    for node_id in topology.cyclic:
        node = topology.nodes[node_id]
        diagnostics.append(_diag(node, DiagnosticReason.LINEAGE_CYCLE))
        for port_name in topology.types[node_id].dataframe_outputs:
            ports[(node_id, port_name)] = PortLineage(
                node_id=node_id,
                node_name=node.name,
                port=port_name,
                status=PortStatus.UNRESOLVED,
                reason=DiagnosticReason.LINEAGE_CYCLE,
                detail="node participates in a DataFrame cycle",
            )

    ordered = tuple(ports[key] for key in sorted(ports, key=lambda item: (item[0], item[1])))
    return ProjectLineage(ports=ordered, truncated=truncated), diagnostics


def _build_topology(
    snapshot: ProjectGraphSnapshot,
    port_types: PortTypeLookup,
    seeds: Mapping[str, Mapping[str, PortColumns]],
    diagnostics: list[ProjectionDiagnostic],
) -> _Topology:
    nodes = {node.ui_id: node for node in snapshot.nodes}
    types: dict[str, NodePortTypes] = {}
    for node in snapshot.nodes:
        resolved = port_types(node.name)
        if resolved is None:
            if node.ui_id in seeds:
                resolved = NodePortTypes(dataframe_outputs=tuple(seeds[node.ui_id]))
            else:
                diagnostics.append(_diag(node, DiagnosticReason.LINEAGE_NODE_DEFINITION_MISSING))
                continue
        if resolved.has_dataframe_ports or resolved.column_inputs or resolved.column_outputs:
            types[node.ui_id] = resolved

    topology = _Topology(nodes=nodes, types=types)
    outgoing: dict[str, set[str]] = {node_id: set() for node_id in types}
    indegree: dict[str, int] = dict.fromkeys(types, 0)
    for edge in snapshot.edges:
        source_types = types.get(edge.source)
        target_types = types.get(edge.target)
        input_name = edge.target_input
        output_name = edge.source_output
        if source_types is None or target_types is None or input_name is None or output_name is None:
            continue
        accepts = input_name in target_types.dataframe_inputs or input_name in target_types.column_inputs
        produces = output_name in source_types.dataframe_outputs or output_name in source_types.column_outputs
        if not (accepts and produces):
            continue
        if (edge.target, input_name) in topology.incoming:
            continue
        topology.incoming[(edge.target, input_name)] = (edge.source, output_name)
        if edge.target not in outgoing[edge.source]:
            outgoing[edge.source].add(edge.target)
            indegree[edge.target] += 1

    queue = deque(sorted(node_id for node_id, degree in indegree.items() if degree == 0))
    while queue:
        node_id = queue.popleft()
        topology.order.append(node_id)
        for target in sorted(outgoing[node_id]):
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
    topology.cyclic = sorted(node_id for node_id in types if node_id not in set(topology.order))
    return topology


def _collect_inputs(
    node_id: str,
    types: NodePortTypes,
    topology: _Topology,
    ports: Mapping[tuple[str, str], PortLineage],
) -> dict[str, PortLineage]:
    inputs: dict[str, PortLineage] = {}
    for input_name in types.dataframe_inputs | types.column_inputs:
        upstream = topology.incoming.get((node_id, input_name))
        if upstream is None:
            continue
        port = ports.get(upstream)
        if port is None:
            source_node = topology.nodes.get(upstream[0])
            port = PortLineage(
                node_id=upstream[0],
                node_name=source_node.name if source_node is not None else "?",
                port=upstream[1],
                status=PortStatus.UNRESOLVED,
                reason=DiagnosticReason.LINEAGE_INPUT_INVALID,
                detail="upstream port lineage is unavailable",
            )
        inputs[input_name] = port
    return inputs


def _finalize(
    node: GraphNode,
    port_name: str,
    role: str,
    result: PortColumns,
    origins: dict[str, LineageRef],
    diagnostics: list[ProjectionDiagnostic],
    max_columns: int,
) -> tuple[PortLineage, bool]:
    seen: set[str] = set()
    columns: list[ColumnLineage] = []
    truncated = False
    for column in result.columns:
        if column.name.startswith(_INTERNAL_PREFIX):
            continue
        if column.name in seen:
            diagnostics.append(_diag(node, DiagnosticReason.LINEAGE_DUPLICATE_COLUMN, f"{port_name}.{column.name}"))
            continue
        if len(columns) >= max_columns:
            truncated = True
            break
        seen.add(column.name)
        own_ref = LineageRef.node_column(node.ui_id, port_name, column.name)
        origin = _origin_for(column, own_ref, origins)
        origins[own_ref.key] = origin
        columns.append(column.with_origin(origin))
    if truncated:
        diagnostics.append(
            _diag(node, DiagnosticReason.LINEAGE_TRUNCATED, f"{port_name}: more than {max_columns} columns")
        )
    port = PortLineage(
        node_id=node.ui_id,
        node_name=node.name,
        port=port_name,
        role=role,
        status=result.status,
        reason=result.reason,
        detail=result.detail,
        columns=tuple(columns),
    )
    return port, truncated


def _origin_for(column: ColumnLineage, own_ref: LineageRef, origins: Mapping[str, LineageRef]) -> LineageRef:
    transparent = (LineageOp.SOURCE, LineageOp.PASS, LineageOp.RENAME)
    if column.op in transparent and len(column.deps) == 1 and not column.deps_unknown:
        dep = column.deps[0]
        if dep.is_dataset_field:
            return dep
        return origins.get(dep.key, dep)
    return own_ref


def _diag(node: GraphNode, reason: DiagnosticReason, detail: str | None = None) -> ProjectionDiagnostic:
    return ProjectionDiagnostic(node_id=node.ui_id, node_name=node.name, reason=reason, detail=detail)


def source_columns_from_fields(
    dataset_id: str,
    fields: list,
    column_filter: tuple[str, ...] | None,
) -> PortColumns:
    """Seed Read-ноды таблицы: активные поля сущности, при фильтре только выбранные."""
    from .sql_mapping import active_fields

    usable = active_fields(fields)
    if not usable:
        return PortColumns.unresolved(
            DiagnosticReason.LINEAGE_SCHEMA_NOT_SYNCED, "dataset fields are not synchronized yet"
        )
    selected = usable
    if column_filter:
        wanted = {name.lower() for name in column_filter}
        selected = [item for item in usable if item.name.lower() in wanted]
    columns = tuple(
        ColumnLineage(
            name=item.name,
            op=LineageOp.SOURCE,
            deps=(LineageRef.dataset_field(dataset_id, item.id),),
            details=details("lineage.source.table", field=item.name),
        )
        for item in selected
    )
    return PortColumns(columns=columns)
