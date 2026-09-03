from __future__ import annotations

from typing import Any

from src.node_dsl.variables.helpers import is_unresolved_value, make_unresolved_value
from src.node_dsl.variables.type_system import (
    coerce_list_variable_value,
    coerce_scalar_variable_value,
    normalize_variable_scalar_target,
)


def normalize_target_type(target_type: Any):
    return normalize_variable_scalar_target(target_type)


def coerce_expression_result(
    value: Any,
    target_type: Any,
    *,
    is_list_type: bool = False,
    allow_unresolved: bool = False,
    allow_none: bool = False,
) -> Any:
    normalized_target_type = normalize_target_type(target_type)
    if normalized_target_type is None:
        return value

    if is_unresolved_value(value):
        return value

    if value is None:
        if allow_none:
            return None
        if allow_unresolved:
            return make_unresolved_value(
                reason=f"Expression result for {normalized_target_type} input cannot be null.",
                declared_type=normalized_target_type,
            )
        raise ValueError(f"Expression result for {normalized_target_type} input cannot be null.")

    try:
        if is_list_type:
            return coerce_list_variable_value(
                value,
                normalized_target_type,
                allow_none=allow_none,
            )
        return coerce_scalar_variable_value(
            value,
            normalized_target_type,
            allow_none=allow_none,
        )
    except ValueError as err:
        error_message = str(err)
        if error_message == "INT variable value must not be boolean.":
            raise ValueError("Expression result for INT input must not be boolean.") from err
        if error_message == "FLOAT variable value must not be boolean.":
            raise ValueError("Expression result for FLOAT input must not be boolean.") from err
        raise
