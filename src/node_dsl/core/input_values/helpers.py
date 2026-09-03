from collections.abc import Iterable, Mapping
from typing import Any

from pydantic import TypeAdapter

from src.node_dsl.input_expressions import (
    ExpressionPolicyRef,
    coerce_expression_result,
    evaluate_input_expression,
)
from src.node_dsl.variables import is_unresolved_value, make_unresolved_value

from .types import (
    NodeInputConstantValue,
    NodeInputExpressionValue,
    NodeInputLinkValue,
    NodeInputValue,
    NodeRuntimeInputValue,
)

_INPUT_VALUE_ADAPTER = TypeAdapter(NodeInputValue)
_LINK_VALUE_ADAPTER = TypeAdapter(NodeInputLinkValue)


def parse_node_input_value(value: Any) -> NodeInputValue | None:
    if isinstance(
        value,
        (
            NodeInputExpressionValue,
            NodeInputConstantValue,
            NodeInputLinkValue,
        ),
    ):
        return value

    if not isinstance(value, Mapping):
        return None

    marker = value.get("__dvt_type")
    if marker is None:
        return None

    if marker not in {"expr", "const", "link"}:
        raise ValueError(f"Unknown dvt_type '{marker}'")

    return _INPUT_VALUE_ADAPTER.validate_python(value)


def parse_node_input_link_value(value: Any) -> NodeInputLinkValue | None:
    if isinstance(value, NodeInputLinkValue):
        return value

    if not isinstance(value, Mapping):
        return None

    marker = value.get("__dvt_type")
    if marker != "link":
        return None

    return _LINK_VALUE_ADAPTER.validate_python(value)


def iter_node_input_link_values(value: Any) -> Iterable[NodeInputLinkValue]:
    link_value = parse_node_input_link_value(value)
    if link_value is not None:
        return (link_value,)

    if not isinstance(value, list):
        return ()

    links: list[NodeInputLinkValue] = []
    for item in value:
        parsed_item = parse_node_input_link_value(item)
        if parsed_item is None:
            return ()
        links.append(parsed_item)

    return tuple(links)


def parse_node_runtime_input_value(value: Any) -> NodeRuntimeInputValue | None:
    parsed_value = parse_node_input_value(value)
    if parsed_value is not None:
        return parsed_value

    link_values = tuple(iter_node_input_link_values(value))
    if link_values:
        return list(link_values)

    return None


def resolve_node_input_value(
        value: Any,
        *,
        variables: Mapping[str, Any] | None = None,
        project_variables: Mapping[str, Any] | None = None,
        target_type: Any = None,
        is_list_type: bool = False,
        allow_expressions: bool = True,
        expression_policy: ExpressionPolicyRef = None,
        allow_unresolved: bool = False,
        allow_none: bool = False,
) -> Any:
    def _unwrap_variable(candidate: Any) -> Any:
        if isinstance(candidate, Mapping) and "name" in candidate and "value" in candidate:
            return candidate["value"]
        if hasattr(candidate, "name") and hasattr(candidate, "value"):
            return getattr(candidate, "value")
        return candidate

    parsed_value = parse_node_input_value(value)
    if isinstance(parsed_value, NodeInputConstantValue):
        return parsed_value.value

    if isinstance(parsed_value, NodeInputExpressionValue):
        if not allow_expressions:
            raise ValueError("Expressions are not enabled for this input.")

        try:
            evaluated_value = evaluate_input_expression(
                expression=parsed_value.value,
                variables={key: _unwrap_variable(item) for key, item in (variables or {}).items()},
                project_variables={
                    key: _unwrap_variable(item)
                    for key, item in (project_variables or {}).items()
                },
                expression_kind=parsed_value.expression_kind,
                expression_policy=expression_policy,
            )
        except (TypeError, ValueError) as err:
            if allow_unresolved:
                return make_unresolved_value(reason=str(err), declared_type=target_type)
            raise

        try:
            return coerce_expression_result(
                evaluated_value,
                target_type=target_type,
                is_list_type=is_list_type,
                allow_unresolved=allow_unresolved,
                allow_none=allow_none,
            )
        except (TypeError, ValueError) as err:
            if allow_unresolved:
                return make_unresolved_value(reason=str(err), declared_type=target_type)
            raise

    if is_unresolved_value(value):
        return value

    return value
