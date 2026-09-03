from __future__ import annotations

from collections.abc import Sequence

from src import enums
from src.modules.pipeline_graph.infra.db_models import GraphEdgeRecord, GraphNodeRecord
from src.node_dsl.core.input_values import (
    NodeInputLinkValue,
    NodeRuntimeInputValue,
    iter_node_input_link_values,
    parse_node_runtime_input_value,
)
from src.node_dsl.registry import definitions as definitions_registry, nodes as nodes_registry
from src.pipeline.types import Pipeline
from src.schemas.internal.node_data import NodeData


def _allows_multiple_connections(node_name: str, input_name: str) -> bool:
    """
    Returns True when a node input supports multiple connections.

    Note: this relies on node definitions registry. If definitions are not available (e.g. early init),
    we fall back to well-known BaseNode multi-inputs.
    """
    try:
        node_def = definitions_registry.get(node_name)
        input_def = node_def.input_definitions.get(input_name)
        if not input_def:
            return False

        return bool(getattr(input_def, "allow_multiple_connections", False))
    except Exception:
        return input_name in {"input_variables", "signal_in"}


def _normalize_graph_input_value(value) -> NodeRuntimeInputValue:
    parsed_value = parse_node_runtime_input_value(value)
    if parsed_value is not None:
        return parsed_value
    raise ValueError("GraphNodeRecord.input_values must use canonical '__dvt_type' payloads.")


def _extract_link_values(value) -> list[NodeInputLinkValue]:
    return list(iter_node_input_link_values(value))


def _resolve_terminal_output_name(node_name: str) -> str:
    """
    Resolve output handle for synthetic ServiceOutputNode link.

    Priority:
    0) node-level terminal output override
    1) canonical "output" (for backwards compatibility with most data nodes)
    2) first non-signal output
    3) "signal_out" (for signal-only nodes like ExecuteSQL)
    4) first available output or fallback "output"
    """
    try:
        node_def = definitions_registry.get(node_name)
        node_class = nodes_registry.get(node_name)
    except Exception:
        return "output"

    output_names = list(node_def.output_definitions.keys())
    if not output_names:
        return "output"

    terminal_output_name = getattr(node_class, "TERMINAL_OUTPUT_NAME", None)
    if terminal_output_name in output_names:
        return terminal_output_name

    if "output" in output_names:
        return "output"

    non_signal_outputs = [
        name
        for name in output_names
        if name not in {"signal_out", "signal_error", "output_variables"}
    ]
    if non_signal_outputs:
        return non_signal_outputs[0]

    if "signal_out" in output_names:
        return "signal_out"

    return output_names[0]


def _normalize_target_nodes(target_nodes: Sequence[str] | None = None) -> list[str]:
    normalized: list[str] = []
    for node_id in target_nodes or []:
        if node_id and node_id not in normalized:
            normalized.append(node_id)
    return normalized


def resolve_service_output_node_id(
    node_id: str,
    target_nodes: Sequence[str] | None = None,
) -> str:
    normalized_target_nodes = _normalize_target_nodes(target_nodes)
    if len(normalized_target_nodes) == 1:
        return "__service_output__"
    return f"__service_output_{node_id}__"


def resolve_execution_target_nodes(
    pipeline: Pipeline,
    target_nodes: Sequence[str] | None = None,
) -> list[str] | None:
    normalized_target_nodes = _normalize_target_nodes(target_nodes)
    if not normalized_target_nodes:
        return None

    execution_target_nodes: list[str] = []
    for node_id in normalized_target_nodes:
        service_node_id = resolve_service_output_node_id(
            node_id,
            target_nodes=normalized_target_nodes,
        )
        execution_target_nodes.append(
            service_node_id if service_node_id in pipeline else node_id
        )
    return execution_target_nodes


def build_pipeline_from_graph(
    nodes: Sequence[GraphNodeRecord],
    edges: Sequence[GraphEdgeRecord],
    target_nodes: Sequence[str] | None = None,
) -> Pipeline:
    pipeline: Pipeline = {}
    normalized_target_nodes = _normalize_target_nodes(target_nodes)
    target_node_ids = set(normalized_target_nodes)

    incoming_edges_map: dict[str, list[GraphEdgeRecord]] = {}
    outgoing_edges_map: dict[str, list[GraphEdgeRecord]] = {}

    for edge in edges:
        incoming_edges_map.setdefault(edge.target, []).append(edge)
        outgoing_edges_map.setdefault(edge.source, []).append(edge)

    for node in nodes:
        inputs: dict[str, NodeRuntimeInputValue] = {}
        input_values = node.input_values or {}

        for input_name, value in input_values.items():
            if value is not None:
                parsed_input_value = _normalize_graph_input_value(value)
                if isinstance(parsed_input_value, NodeInputLinkValue):
                    continue
                inputs[input_name] = parsed_input_value

        for edge in incoming_edges_map.get(node.ui_id, []):
            target_handle = edge.target_handle.replace("input-", "") if edge.target_handle else None
            source_node_id = edge.source
            source_handle = edge.source_handle.replace("output-", "") if edge.source_handle else None

            if target_handle and source_node_id and source_handle:
                new_link = NodeInputLinkValue(node_id=source_node_id, output_name=source_handle)

                if target_handle in inputs:
                    existing_val = inputs[target_handle]
                    existing_links = _extract_link_values(existing_val)
                    if _allows_multiple_connections(node.name, target_handle):
                        if existing_links:
                            inputs[target_handle] = [*existing_links, new_link]
                            continue

                inputs[target_handle] = new_link

        pipeline[node.ui_id] = NodeData(
            name=node.name,
            store_enabled=node.store_enabled,
            inputs=inputs,
        )

    candidates = [n for n in nodes if n.ui_id in target_node_ids] if normalized_target_nodes else nodes

    for node in candidates:
        if node.type == enums.NodeType.WIDGET.value.lower():
            continue
        is_target_node = bool(normalized_target_nodes) and node.ui_id in target_node_ids
        is_empty_output = not normalized_target_nodes and node.ui_id not in outgoing_edges_map

        if is_target_node or is_empty_output:
            try:
                node_class = nodes_registry.get(node.name)
            except Exception:
                continue

            if is_target_node and not node_class.CAN_BE_OUTPUT_NODE:
                raise ValueError(f"{node.name} cannot be used as an explicit target node.")

            service_node_id = resolve_service_output_node_id(
                node.ui_id,
                target_nodes=normalized_target_nodes,
            )
            source_output_name = _resolve_terminal_output_name(node.name)

            pipeline[service_node_id] = NodeData(
                name="ServiceOutputNode",
                inputs={
                    "input": NodeInputLinkValue(
                        node_id=node.ui_id,
                        output_name=source_output_name,
                    )
                },
            )

    return pipeline
