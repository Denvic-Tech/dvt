from __future__ import annotations

import json
import re
import types
from datetime import datetime, timedelta, date
from decimal import Decimal
from numbers import Integral, Real
from typing import Union, cast, Any, get_origin, Annotated, get_args

from pydantic import TypeAdapter

from core.types import DataType
from src.node_dsl.node_typing import IO
from src.node_dsl.variables.constants import (
    EXPRESSION_VARIABLE_SCALAR_IOS,
    LIST_VARIABLE_SCALAR_IOS,
    VARIABLE_SCALAR_IOS,
)
from src.node_dsl.variables.types import VariableType

_VARIABLE_SCALAR_IO_SET = frozenset(VARIABLE_SCALAR_IOS)
_EXPRESSION_VARIABLE_SCALAR_IO_SET = frozenset(EXPRESSION_VARIABLE_SCALAR_IOS)
_LIST_VARIABLE_SCALAR_IO_SET = frozenset(LIST_VARIABLE_SCALAR_IOS)
_VARIABLE_SCALAR_VALUES: tuple[str, ...] = tuple(io_type.value for io_type in VARIABLE_SCALAR_IOS)
_NONE_TYPE = type(None)
_UNION_ORIGINS = {Union, types.UnionType, getattr(types, "UnionType", None)}
_JSON_ORIGINS = {dict, list}
_INT_ADAPTER = TypeAdapter(int)
_FLOAT_ADAPTER = TypeAdapter(float)
_BOOL_ADAPTER = TypeAdapter(bool)
_DATETIME_ADAPTER = TypeAdapter(datetime)
_TIMEDELTA_ADAPTER = TypeAdapter(timedelta)
_HUMAN_TIMEDELTA_RE = re.compile(
    r"""
    ^\s*
    (?P<sign>[+-])?
    \s*
    (?:
        (?:(?P<weeks>\d+)\s*w(?:eeks?)?\s*)?
        (?:(?P<days>\d+)\s*d(?:ays?)?\s*)?
        (?:(?P<hours>\d+)\s*h(?:ours?)?\s*)?
        (?:(?P<minutes>\d+)\s*m(?:in(?:utes?)?)?\s*)?
        (?:(?P<seconds>\d+)\s*s(?:ec(?:onds?)?)?\s*)?
    )
    \s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)


def get_variable_scalar_type_values() -> tuple[str, ...]:
    return _VARIABLE_SCALAR_VALUES


def normalize_variable_scalar_type(variable_type: IO | str) -> VariableType:
    try:
        normalized_type = (
            variable_type if isinstance(variable_type, IO) else IO(str(variable_type))
        )
    except ValueError as err:
        raise ValueError(f"Unsupported variable type '{variable_type}'.") from err

    if normalized_type not in _VARIABLE_SCALAR_IO_SET:
        raise ValueError(f"Unsupported variable type '{normalized_type}'.")

    return cast(VariableType, normalized_type)


def normalize_variable_scalar_target(target_type: Any) -> VariableType | None:
    if target_type is None:
        return None

    if isinstance(target_type, list):
        target_type = target_type[0] if target_type else None
        if target_type is None:
            return None

    value = getattr(target_type, "value", target_type)
    if not isinstance(value, str | IO):
        return None

    try:
        return normalize_variable_scalar_type(value)
    except ValueError:
        return None


def is_variable_scalar_type(variable_type: Any) -> bool:
    try:
        normalize_variable_scalar_type(variable_type)
    except ValueError:
        return False
    return True


def ensure_expression_supported_variable_type(variable_type: IO | str) -> VariableType:
    normalized_type = normalize_variable_scalar_type(variable_type)
    if normalized_type not in _EXPRESSION_VARIABLE_SCALAR_IO_SET:
        raise ValueError(
            "Expressions are supported only for STRING/BOOLEAN/INT/FLOAT/DATETIME/TIMEDELTA "
            f"variables, got '{normalized_type}'."
        )
    return normalized_type


def ensure_list_supported_variable_type(variable_type: IO | str) -> VariableType:
    normalized_type = normalize_variable_scalar_type(variable_type)
    if normalized_type not in _LIST_VARIABLE_SCALAR_IO_SET:
        raise ValueError(
            "List variables are supported only for STRING/BOOLEAN/INT/FLOAT/DATETIME/TIMEDELTA "
            f"types, got '{normalized_type}'."
        )
    return normalized_type


def parse_human_timedelta(value: str) -> timedelta | None:
    match = _HUMAN_TIMEDELTA_RE.match(value)
    if not match:
        return None

    parts = match.groupdict(default="0")
    sign = -1 if parts["sign"] == "-" else 1

    td = timedelta(
        weeks=int(parts["weeks"]),
        days=int(parts["days"]),
        hours=int(parts["hours"]),
        minutes=int(parts["minutes"]),
        seconds=int(parts["seconds"]),
    )
    return td * sign


def coerce_timedelta_value(value: Any) -> timedelta:
    if isinstance(value, timedelta):
        return value

    if isinstance(value, str):
        human_td = parse_human_timedelta(value)
        if human_td is not None:
            return human_td

    return _TIMEDELTA_ADAPTER.validate_python(value)


def coerce_scalar_variable_value(
    value: Any,
    variable_type: IO | str,
    *,
    allow_none: bool = False,
) -> Any:
    normalized_type = normalize_variable_scalar_type(variable_type)

    if value is None:
        if allow_none:
            return None
        raise ValueError(f"{normalized_type} variable value cannot be null.")

    if normalized_type is IO.STRING:
        return str(value)

    if normalized_type is IO.BOOLEAN:
        return _BOOL_ADAPTER.validate_python(value)

    if normalized_type is IO.INT:
        if isinstance(value, bool):
            raise ValueError("INT variable value must not be boolean.")
        return _INT_ADAPTER.validate_python(value)

    if normalized_type is IO.FLOAT:
        if isinstance(value, bool):
            raise ValueError("FLOAT variable value must not be boolean.")
        return _FLOAT_ADAPTER.validate_python(value)

    if normalized_type is IO.DATETIME:
        return _DATETIME_ADAPTER.validate_python(value)

    if normalized_type is IO.TIMEDELTA:
        return coerce_timedelta_value(value)

    return value


def normalize_variable_list_items(
    value: Any,
    *,
    parse_json_strings: bool = False,
) -> list[Any]:
    if isinstance(value, str):
        if not parse_json_strings:
            raise ValueError("List variable value must be a list-like value, got string.")
        try:
            decoded_value = json.loads(value)
        except json.JSONDecodeError as err:
            raise ValueError("List variable value must be a list-like value, got string.") from err
        value = decoded_value

    if isinstance(value, tuple):
        value = list(value)
    elif isinstance(value, set):
        value = sorted(value)

    if not isinstance(value, list):
        raise ValueError(f"List variable value must be a list-like value, got {type(value).__name__}.")

    return value


def coerce_list_variable_value(
    value: Any,
    variable_type: IO | str,
    *,
    allow_none: bool = False,
    parse_json_strings: bool = False,
) -> list[Any] | None:
    normalized_type = ensure_list_supported_variable_type(variable_type)

    if value is None:
        if allow_none:
            return None
        raise ValueError("List variable value cannot be null.")

    normalized_items = normalize_variable_list_items(
        value,
        parse_json_strings=parse_json_strings,
    )
    coerced_items: list[Any] = []
    for item in normalized_items:
        if item is None:
            raise ValueError("List variable items cannot be null.")
        coerced_items.append(coerce_scalar_variable_value(item, normalized_type, allow_none=False))
    return coerced_items


def infer_variable_scalar_type_from_value(
    value: Any,
    *,
    default: VariableType = IO.JSON,
) -> VariableType:
    if isinstance(value, bool):
        return IO.BOOLEAN
    if isinstance(value, Integral):
        return IO.INT
    if isinstance(value, (Decimal, Real)):
        return IO.FLOAT
    if isinstance(value, (datetime, date)):
        return IO.DATETIME
    if isinstance(value, timedelta):
        return IO.TIMEDELTA
    if isinstance(value, str):
        return IO.STRING
    if isinstance(value, (dict, list, tuple, set)):
        return IO.JSON
    return default


def infer_list_item_variable_type_from_value(items: list[Any]) -> VariableType:
    if not items:
        raise ValueError("Cannot infer list item type from an empty list. Set `target_dtype` explicitly.")

    inferred_types: set[VariableType] = set()
    for item in items:
        if item is None:
            raise ValueError("Cannot infer list item type when list contains null items.")
        inferred_item_type = infer_variable_scalar_type_from_value(item)
        if inferred_item_type not in _LIST_VARIABLE_SCALAR_IO_SET:
            raise ValueError(
                "List variables support only STRING/BOOLEAN/INT/FLOAT/DATETIME/TIMEDELTA items."
            )
        inferred_types.add(inferred_item_type)

    if len(inferred_types) != 1:
        raise ValueError(
            "Cannot infer list item type from a mixed list. Set `target_dtype` explicitly."
        )

    return next(iter(inferred_types))


def infer_variable_scalar_type_from_data_type(data_type: DataType) -> VariableType | None:
    if data_type == DataType.INT:
        return IO.INT
    if data_type == DataType.FLOAT:
        return IO.FLOAT
    if data_type == DataType.STRING:
        return IO.STRING
    if data_type == DataType.BOOLEAN:
        return IO.BOOLEAN
    if data_type == DataType.DATETIME:
        return IO.DATETIME
    if data_type == DataType.TIMEDELTA:
        return IO.TIMEDELTA
    if data_type == DataType.CATEGORY:
        return IO.STRING
    if data_type in {DataType.DICTIONARY, DataType.OBJECT}:
        return IO.JSON
    return None


def infer_variable_scalar_type_from_python_type(python_type: Any) -> VariableType | None:
    if python_type is bool:
        return IO.BOOLEAN
    if python_type is int:
        return IO.INT
    if python_type is float or python_type is Decimal:
        return IO.FLOAT
    if python_type is datetime or python_type is date:
        return IO.DATETIME
    if python_type is timedelta:
        return IO.TIMEDELTA
    if python_type is str:
        return IO.STRING

    origin = get_origin(python_type)
    if python_type in _JSON_ORIGINS or origin in _JSON_ORIGINS:
        return IO.JSON
    return None


def infer_variable_scalar_type_from_type_name(type_name: str) -> VariableType | None:
    normalized = (type_name or "").strip().lower()
    if not normalized:
        return None

    if "timedelta" in normalized or "interval" in normalized:
        return IO.TIMEDELTA
    if "datetime" in normalized or "timestamp" in normalized or normalized == "date":
        return IO.DATETIME
    if (
        " bool" in f" {normalized}"
        or normalized.startswith("bool")
        or "boolean" in normalized
        or normalized == "bit"
    ):
        return IO.BOOLEAN
    if any(token in normalized for token in ("tinyint", "smallint", "bigint", "integer", "serial")):
        return IO.INT
    if normalized.endswith("int") or normalized.startswith("int") or " int" in normalized:
        return IO.INT
    if any(
        token in normalized
        for token in ("decimal", "numeric", "float", "double", "real", "money", "number")
    ):
        return IO.FLOAT
    if any(
        token in normalized
        for token in ("json", "dict", "map", "struct", "array", "object", "variant")
    ):
        return IO.JSON
    if any(token in normalized for token in ("char", "text", "clob", "string", "uuid", "xml")):
        return IO.STRING
    if normalized == "time":
        return IO.DATETIME
    return None


def infer_variable_scalar_type_from_metadata_type(raw_type: Any) -> VariableType | None:
    if raw_type is None:
        return None

    if variable_type := infer_variable_scalar_type_from_python_type(raw_type):
        return variable_type

    python_type = None
    try:
        python_type = getattr(raw_type, "python_type", None)
    except NotImplementedError:
        python_type = None

    if variable_type := infer_variable_scalar_type_from_python_type(python_type):
        return variable_type

    if variable_type := infer_variable_scalar_type_from_type_name(str(raw_type)):
        return variable_type

    if variable_type := infer_variable_scalar_type_from_type_name(type(raw_type).__name__):
        return variable_type

    return infer_variable_scalar_type_from_data_type(DataType.from_type(raw_type))


def _strip_annotated(annotation: Any) -> Any:
    if get_origin(annotation) is Annotated:
        return _strip_annotated(get_args(annotation)[0])
    return annotation


def _is_json_annotation(annotation: Any) -> bool:
    annotation = _strip_annotated(annotation)
    origin = get_origin(annotation)
    return annotation in _JSON_ORIGINS or origin in _JSON_ORIGINS


def infer_variable_scalar_type_from_annotation(annotation: Any) -> VariableType | None:
    annotation = _strip_annotated(annotation)
    origin = get_origin(annotation)

    if origin in _UNION_ORIGINS:
        union_args = tuple(
            _strip_annotated(arg)
            for arg in get_args(annotation)
            if arg is not _NONE_TYPE
        )
        if len(union_args) == 1:
            return infer_variable_scalar_type_from_annotation(union_args[0])
        if union_args and all(_is_json_annotation(arg) for arg in union_args):
            return IO.JSON
        return None

    if _is_json_annotation(annotation):
        return IO.JSON

    return infer_variable_scalar_type_from_python_type(annotation)
