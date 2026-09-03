from datetime import datetime, timedelta
from typing import Any, Mapping

from pydantic import TypeAdapter

from src.node_dsl.node_typing import IO
from src.node_dsl.variables import coerce_variable_value, normalize_variable_type
from src.node_dsl.variables.type_system import infer_variable_scalar_type_from_value
from src.node_dsl.variables.types import VariableType

_TIMEDELTA_JSON_ADAPTER = TypeAdapter(timedelta)


def is_typed_project_variable_payload(value: Any) -> bool:
    return isinstance(value, Mapping) and "type" in value and "value" in value


def deserialize_project_variable_value(
    *,
    variable_type: VariableType | IO | str,
    value: Any,
    is_list_type: bool = False,
) -> Any:
    normalized_type = normalize_variable_type(variable_type)
    return coerce_variable_value(
        value,
        normalized_type,
        allow_none=True,
        is_list_type=is_list_type,
    )


def _serialize_scalar_project_variable_value(
    *,
    variable_type: VariableType,
    value: Any,
) -> Any:
    if value is None:
        return None
    if variable_type is IO.DATETIME:
        if not isinstance(value, datetime):
            raise TypeError(f"Expected datetime value, got {type(value).__name__}.")
        return value.isoformat()
    if variable_type is IO.TIMEDELTA:
        if not isinstance(value, timedelta):
            raise TypeError(f"Expected timedelta value, got {type(value).__name__}.")
        return _TIMEDELTA_JSON_ADAPTER.dump_python(value, mode="json")
    return value


def serialize_project_variable_value(
    *,
    variable_type: VariableType | IO | str,
    value: Any,
    is_list_type: bool = False,
) -> Any:
    normalized_type = normalize_variable_type(variable_type)
    runtime_value = deserialize_project_variable_value(
        variable_type=normalized_type,
        value=value,
        is_list_type=is_list_type,
    )
    if runtime_value is None:
        return None
    if is_list_type:
        return [
            _serialize_scalar_project_variable_value(
                variable_type=normalized_type,
                value=item,
            )
            for item in runtime_value
        ]
    return _serialize_scalar_project_variable_value(
        variable_type=normalized_type,
        value=runtime_value,
    )


def normalize_project_variable_storage_payload(
    payload: Any,
    *,
    allow_legacy: bool = False,
) -> dict[str, Any]:
    if is_typed_project_variable_payload(payload):
        raw_type = payload["type"]
        raw_value = payload.get("value")
        is_list_type = bool(payload.get("is_list_type", False))
    elif allow_legacy:
        raw_type = infer_variable_scalar_type_from_value(payload)
        raw_value = payload
        is_list_type = False
    else:
        raise ValueError("Project variable payload must define explicit 'type' and 'value'.")

    normalized_type = normalize_variable_type(raw_type)
    normalized_value = serialize_project_variable_value(
        variable_type=normalized_type,
        value=raw_value,
        is_list_type=is_list_type,
    )
    return {
        "type": normalized_type.value,
        "value": normalized_value,
        "is_list_type": is_list_type,
    }


def normalize_project_variables_storage_map(
    variables: Mapping[str, Any] | None,
    *,
    allow_legacy: bool = False,
) -> dict[str, dict[str, Any]] | None:
    if variables is None:
        return None

    normalized: dict[str, dict[str, Any]] = {}
    for key, payload in variables.items():
        if not isinstance(key, str) or not key:
            raise ValueError("Project variable key must be a non-empty string.")
        normalized[key] = normalize_project_variable_storage_payload(
            payload,
            allow_legacy=allow_legacy,
        )
    return normalized
