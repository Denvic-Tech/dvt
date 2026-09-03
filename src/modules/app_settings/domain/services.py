from __future__ import annotations

import json
import operator
import types
from collections.abc import Callable
from functools import reduce
from typing import Annotated, Any, Union, get_args, get_origin

from .definitions import SettingDefinition
from .exceptions import SettingValidationError


def unwrap_annotated(annotation: Any) -> Any:
    if get_origin(annotation) is Annotated:
        args = get_args(annotation)
        if args:
            return args[0]
    return annotation


def strip_optional(annotation: Any) -> tuple[Any, bool]:
    annotation = unwrap_annotated(annotation)
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin in (Union, types.UnionType) and type(None) in args:
        non_none = tuple(arg for arg in args if arg is not type(None))
        if len(non_none) == 1:
            return unwrap_annotated(non_none[0]), True
        if non_none:
            return reduce(operator.or_, (unwrap_annotated(arg) for arg in non_none)), True
    return annotation, False


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "1", "on"}:
            return True
        if normalized in {"false", "no", "0", "off"}:
            return False
    raise ValueError("value must be a boolean")


def _coerce_model(annotation: Any, value: Any) -> Any:
    try:
        if isinstance(value, annotation):
            return value
    except TypeError:
        pass

    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        raise ValueError("value must be an object")

    model_validate = getattr(annotation, "model_validate", None)
    if callable(model_validate):
        return model_validate(value)
    return annotation(**value)


def _is_model_annotation(annotation: Any) -> bool:
    return isinstance(annotation, type) and callable(getattr(annotation, "model_validate", None))


def coerce_setting_value(definition: SettingDefinition, value: Any) -> Any:
    annotation, optional = strip_optional(definition.type_)
    if value == "" and optional:
        value = None
    if value is None:
        if optional:
            return None
        raise SettingValidationError(f"{definition.key}: value is required")

    try:
        if annotation is bool:
            coerced = _coerce_bool(value)
        elif annotation is int:
            coerced = int(value)
        elif annotation is float:
            coerced = float(value)
        elif annotation is str:
            coerced = value if isinstance(value, str) else str(value)
        elif _is_model_annotation(annotation):
            coerced = _coerce_model(annotation, value)
        elif callable(annotation):
            coerced = annotation(value)
        else:
            coerced = value
    except Exception as exc:
        raise SettingValidationError(f"{definition.key}: invalid value: {exc}") from exc

    validate_constraints(definition, coerced)
    return coerced


def validate_constraints(definition: SettingDefinition, value: Any) -> None:
    if value is None:
        return
    if definition.ge is not None and value < definition.ge:
        raise SettingValidationError(f"{definition.key}: value must be >= {definition.ge}")
    if definition.le is not None and value > definition.le:
        raise SettingValidationError(f"{definition.key}: value must be <= {definition.le}")
    if definition.min_length is not None and len(value) < definition.min_length:
        raise SettingValidationError(
            f"{definition.key}: value length must be >= {definition.min_length}"
        )
    if definition.max_length is not None and len(value) > definition.max_length:
        raise SettingValidationError(
            f"{definition.key}: value length must be <= {definition.max_length}"
        )


def infer_setup_type(key: str, definition: SettingDefinition) -> str:
    if definition.setup_type:
        return definition.setup_type
    if definition.secret or "password" in key.lower():
        return "password"
    annotation, _ = strip_optional(definition.type_)
    if annotation is bool:
        return "boolean"
    if annotation in {int, float}:
        return "number"
    return "text"


def is_required_unfilled(value_getter: Callable[[str], Any], definition: SettingDefinition) -> bool:
    if not definition.required:
        return False
    value = value_getter(definition.key)
    return not bool(value)
