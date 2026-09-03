from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.constants import UNSET
from src.types.common import UnsetType

from .type_system import (
    coerce_list_variable_value,
    coerce_scalar_variable_value,
    ensure_expression_supported_variable_type as ensure_expression_supported_scalar_variable_type,
    ensure_list_supported_variable_type,
    normalize_variable_scalar_type,
)
from .types import (
    UnresolvedValue,
    VariableDescriptorMetadata,
    VariableMapMetadata,
    VariableOutput,
    VariableType,
)


def normalize_variable_type(variable_type):
    return normalize_variable_scalar_type(variable_type)


def ensure_expression_supported_variable_type(variable_type):
    return ensure_expression_supported_scalar_variable_type(variable_type)


def is_unresolved_value(value: Any) -> bool:
    return isinstance(value, UnresolvedValue)


def make_unresolved_value(
    *,
    reason: str | None = None,
    declared_type: VariableType | str | None = None,
    is_list_type: bool = False,
) -> UnresolvedValue:
    normalized_declared_type = None
    if declared_type is not None:
        normalized_declared_type = str(getattr(declared_type, "value", declared_type))
    return UnresolvedValue(
        reason=reason,
        declared_type=normalized_declared_type,
        is_list_type=is_list_type,
    )


def default_is_set(default_value: Any | UnsetType) -> bool:
    return default_value != UNSET


def resolve_literal_input_value(raw_value: Any, *, field_name: str) -> Any:
    from src.node_dsl.core.input_values import NodeInputConstantValue, parse_node_input_value

    parsed_value = parse_node_input_value(raw_value)
    if isinstance(parsed_value, NodeInputConstantValue):
        return parsed_value.value
    if parsed_value is not None:
        raise ValueError(f"`{field_name}` must be a literal value.")
    return raw_value


def apply_nullable_default_policy(
    value: Any,
    *,
    nullable: bool = False,
    default_value: Any | UnsetType = UNSET,
    default_resolver: Callable[[Any], Any] | None = None,
    null_error_message: str = "Value resolved to null.",
) -> Any:
    if is_unresolved_value(value):
        return value

    if value is not None:
        return value

    if default_is_set(default_value):
        literal_default = resolve_literal_input_value(default_value, field_name="default")
        return default_resolver(literal_default) if default_resolver is not None else literal_default

    if nullable:
        return None

    raise ValueError(null_error_message)


def build_variable_map_metadata(value: Any) -> VariableMapMetadata:
    descriptors: list[VariableDescriptorMetadata] = []

    if isinstance(value, dict):
        items = sorted(
            (
                (name, payload)
                for name, payload in value.items()
                if isinstance(name, str) and name
            ),
            key=lambda item: item[0],
        )
    elif hasattr(value, "name") and getattr(value, "name", None):
        items = [(value.name, value)]
    else:
        items = []

    for variable_name, payload in items:
        variable_output = build_variable_output(variable_name, payload)
        descriptors.append(
            VariableDescriptorMetadata(
                name=variable_output.name,
                type=variable_output.type,
                var_type=variable_output.var_type,
                is_list_type=variable_output.is_list_type,
                value_state="unresolved" if is_unresolved_value(variable_output.value) else "resolved",
            )
        )

    return VariableMapMetadata(variables=descriptors)


def coerce_variable_value(
    value: Any,
    variable_type,
    *,
    allow_none: bool = False,
    is_list_type: bool = False,
    parse_json_strings: bool = False,
) -> Any:
    if is_unresolved_value(value):
        return value
    if is_list_type:
        return coerce_list_variable_value(
            value,
            variable_type,
            allow_none=allow_none,
            parse_json_strings=parse_json_strings,
        )
    return coerce_scalar_variable_value(value, variable_type, allow_none=allow_none)


def build_variable_output(name: str, payload: VariableOutput | dict[str, Any]) -> VariableOutput:
    if isinstance(payload, VariableOutput):
        if payload.name != name:
            raise ValueError(
                f"Variable payload name '{payload.name}' does not match key '{name}'."
            )
        return payload

    if not isinstance(payload, dict):
        raise ValueError(f"Variable '{name}' must be a VariableOutput or mapping payload.")

    payload_name = payload.get("name", name)
    if payload_name != name:
        raise ValueError(
            f"Variable payload name '{payload_name}' does not match key '{name}'."
        )

    variable_type = normalize_variable_type(payload.get("type"))
    is_list_type = bool(payload.get("is_list_type", False))
    if is_list_type:
        ensure_list_supported_variable_type(variable_type)

    variable_scope = payload.get("var_type", "user")
    if variable_scope not in {"user", "system"}:
        raise ValueError(f"Variable '{name}' has unsupported var_type '{variable_scope}'.")

    return VariableOutput(
        name=name,
        type=variable_type,
        value=payload.get("value"),
        var_type=variable_scope,
        is_list_type=is_list_type,
    )


def resolve_variable_runtime_value(
    raw_value: Any,
    *,
    variables: dict[str, Any] | None,
    variable_type: "VariableType",
    allow_unresolved: bool = False,
    nullable: bool = False,
    default_value: Any | UnsetType = UNSET,
    is_list_type: bool = False,
    **legacy_kwargs: Any,
) -> Any:
    from src.node_dsl.core.input_values import (
        NodeInputConstantValue,
        NodeInputExpressionValue,
        parse_node_input_value,
        resolve_node_input_value,
    )

    forced_default_is_set = legacy_kwargs.pop("default_is_set", None)
    if legacy_kwargs:
        unknown_kwargs = ", ".join(sorted(legacy_kwargs))
        raise TypeError(f"Unexpected keyword arguments: {unknown_kwargs}")

    effective_default_value = (
        default_value
        if forced_default_is_set is True or default_is_set(default_value)
        else UNSET
    )
    normalized_type = normalize_variable_type(variable_type)
    if is_list_type:
        ensure_list_supported_variable_type(normalized_type)
    parsed_value = parse_node_input_value(raw_value)

    if isinstance(parsed_value, NodeInputExpressionValue):
        if is_list_type and parsed_value.expression_kind != "single":
            error_message = "List variables support only single expressions."
            if allow_unresolved:
                return make_unresolved_value(
                    reason=error_message,
                    declared_type=normalized_type,
                    is_list_type=True,
                )
            raise ValueError(error_message)
        try:
            if not is_list_type:
                ensure_expression_supported_variable_type(normalized_type)
        except ValueError as err:
            if allow_unresolved:
                return make_unresolved_value(
                    reason=str(err),
                    declared_type=normalized_type,
                    is_list_type=is_list_type,
                )
            raise
        resolved_value = resolve_node_input_value(
            parsed_value,
            variables=variables,
            target_type=None if is_list_type else normalized_type,
            allow_expressions=True,
            expression_policy="default",
            allow_unresolved=allow_unresolved,
            allow_none=True,
        )
        if is_unresolved_value(resolved_value):
            return make_unresolved_value(
                reason=resolved_value.reason,
                declared_type=normalized_type,
                is_list_type=True,
            )
        try:
            coerced_value = coerce_variable_value(
                resolved_value,
                normalized_type,
                allow_none=True,
                is_list_type=is_list_type,
            )
        except ValueError as err:
            if allow_unresolved:
                return make_unresolved_value(
                    reason=str(err),
                    declared_type=normalized_type,
                    is_list_type=is_list_type,
                )
            raise
        return apply_nullable_default_policy(
            coerced_value,
            nullable=nullable,
            default_value=effective_default_value,
            default_resolver=lambda literal: coerce_variable_value(
                literal,
                normalized_type,
                allow_none=True,
                is_list_type=is_list_type,
            ),
            null_error_message=(
                "List variable value cannot be null."
                if is_list_type
                else f"{normalized_type} variable value cannot be null."
            ),
        )

    if isinstance(parsed_value, NodeInputConstantValue):
        resolved_value = coerce_variable_value(
            parsed_value.value,
            normalized_type,
            allow_none=True,
            is_list_type=is_list_type,
        )
        return apply_nullable_default_policy(
            resolved_value,
            nullable=nullable,
            default_value=effective_default_value,
            default_resolver=lambda literal: coerce_variable_value(
                literal,
                normalized_type,
                allow_none=True,
                is_list_type=is_list_type,
            ),
            null_error_message=(
                "List variable value cannot be null."
                if is_list_type
                else f"{normalized_type} variable value cannot be null."
            ),
        )

    if parsed_value is not None:
        raise ValueError("Variable links are not supported when defining variable values.")

    resolved_value = coerce_variable_value(
        raw_value,
        normalized_type,
        allow_none=True,
        is_list_type=is_list_type,
    )
    return apply_nullable_default_policy(
        resolved_value,
        nullable=nullable,
        default_value=effective_default_value,
        default_resolver=lambda literal: coerce_variable_value(
            literal,
            normalized_type,
            allow_none=True,
            is_list_type=is_list_type,
        ),
        null_error_message=(
            "List variable value cannot be null."
            if is_list_type
            else f"{normalized_type} variable value cannot be null."
        ),
    )
