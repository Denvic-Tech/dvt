"""MCP-specific node policies and advisory diagnostics."""

from src.node_dsl.core.input_values import NodeInputValues, parse_node_input_value

from .diagnostics import Diagnostic
from .state import GraphState

GENERIC_CODE_NODES = frozenset({"ExecutePython", "DataFrameExecCode", "ExecuteSQL"})


def read_table_configuration_errors(
    *,
    node_id: str,
    inputs: NodeInputValues,
) -> list[Diagnostic]:
    errors: list[Diagnostic] = []

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
    if (
        not isinstance(columns, list)
        or not columns
        or not all(isinstance(column, str) and column.strip() for column in columns)
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


def generic_code_errors(graph: GraphState, touched_node_ids: set[str]) -> list[Diagnostic]:
    return [
        {"code": "GENERIC_CODE_COMMENT_REQUIRED", "node_id": node_id}
        for node_id in touched_node_ids
        if not (graph.nodes[node_id].comment or "").strip()
    ]


def graph_warnings(graph: GraphState) -> list[Diagnostic]:
    generic_ids = sorted(
        node.id for node in graph.nodes.values() if node.node_type in GENERIC_CODE_NODES
    )
    warnings = [
        {"code": "GENERIC_CODE_NODE", "severity": "high", "node_id": node_id}
        for node_id in generic_ids
    ]
    if generic_ids and len(generic_ids) * 2 >= len(graph.nodes):
        warnings.append({"code": "GENERIC_CODE_HEAVY_GRAPH", "severity": "high"})
    for node in graph.nodes.values():
        if not (node.display_name or "").strip():
            warnings.append({"code": "MISSING_DISPLAY_NAME", "node_id": node.id})
        if not (node.comment or "").strip():
            warnings.append({"code": "MISSING_COMMENT", "node_id": node.id})
    return warnings
