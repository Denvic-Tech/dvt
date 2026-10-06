"""Conversion of user-supplied input values at the MCP boundary."""

from typing import Any

from src.node_dsl.core.input_values import (
    NodeInputConstantValue,
    NodeInputExpressionValue,
    NodeInputValue,
    parse_node_input_value,
)

from .schemas import InputValueSchema


def canonical_input(value: InputValueSchema) -> NodeInputValue:
    if value.kind == "constant":
        return NodeInputConstantValue.model_validate({"__dvt_type": "const", "value": value.value})
    if value.kind == "expression":
        if not isinstance(value.value, str) or not value.value.strip():
            raise ValueError("Expression input requires a non-empty string value.")
        return NodeInputExpressionValue.model_validate(
            {
                "__dvt_type": "expr",
                "value": value.value,
                "expression_kind": value.expression_kind,
            }
        )
    if not value.connection_id:
        raise ValueError("connection_ref input requires connection_id.")
    return NodeInputConstantValue.model_validate(
        {"__dvt_type": "const", "value": value.connection_id}
    )


def ai_input(value: Any, *, accessible_connection_ids: set[str]) -> dict[str, Any]:
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
