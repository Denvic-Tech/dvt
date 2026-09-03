from __future__ import annotations

import dataclasses
from dataclasses import MISSING
from typing import Any

from .hasher import _new_hasher
from .utils import _finalize, _to_bytes_fast, _update_many


def _type_tag(tp: Any) -> str:
    module = getattr(tp, "__module__", None)
    qualname = getattr(tp, "__qualname__", None)

    if module and qualname:
        return f"{module}:{qualname}"

    return repr(tp)


def _callable_tag(fn: Any) -> str:
    module = getattr(fn, "__module__", None)
    qualname = getattr(fn, "__qualname__", None)

    if module and qualname:
        return f"{module}:{qualname}"

    return repr(fn)


def _get_dataclass_model_hash(cls: type) -> bytes:
    """
    Хэш схемы dataclass-класса:
      - class tag
      - dataclass params
      - имена полей
      - типы полей
      - default/default_factory
      - основные field-флаги
    """
    h = _new_hasher()

    cls_tag = f"{cls.__module__}:{cls.__qualname__}"
    params = getattr(cls, "__dataclass_params__", None)

    params_payload = {}
    if params is not None:
        for name in (
            "init",
            "repr",
            "eq",
            "order",
            "unsafe_hash",
            "frozen",
            "match_args",
            "kw_only",
            "slots",
            "weakref_slot",
        ):
            if hasattr(params, name):
                params_payload[name] = getattr(params, name)

    fields_payload: list[dict[str, Any]] = []

    for field in dataclasses.fields(cls):
        if field.default is not MISSING:
            default_kind = "value"
            default_value = _to_bytes_fast(field.default).hex()
        elif field.default_factory is not MISSING:  # type: ignore[attr-defined]
            default_kind = "factory"
            default_value = _callable_tag(field.default_factory)  # type: ignore[attr-defined]
        else:
            default_kind = "missing"
            default_value = None

        fields_payload.append(
            {
                "name": field.name,
                "type": _type_tag(field.type),
                "default_kind": default_kind,
                "default_value": default_value,
                "init": field.init,
                "repr": field.repr,
                "hash": field.hash,
                "compare": field.compare,
                "kw_only": field.kw_only,
            }
        )

    payload = {
        "kind": "dataclass_model",
        "class": cls_tag,
        "params": params_payload,
        "fields": fields_payload,
    }

    _update_many(h, [_to_bytes_fast(payload)])
    return _finalize(h)


def _get_dataclass_object_hash(obj: Any, deep: bool = False) -> bytes:
    """
    Хэш dataclass-инстанса:
      - class tag
      - field name
      - hash(field value)
    """
    from .get_hash import get_hash  # локально, чтобы не ловить circular import

    h = _new_hasher()

    cls = obj.__class__
    cls_tag = f"{cls.__module__}:{cls.__qualname__}"

    fields_payload: list[tuple[str, str]] = []

    for field in dataclasses.fields(obj):
        value = getattr(obj, field.name)
        value_hash = get_hash(value, deep=deep).hex()
        fields_payload.append((field.name, value_hash))

    payload = {
        "kind": "dataclass_object",
        "class": cls_tag,
        "fields": fields_payload,
    }

    _update_many(h, [_to_bytes_fast(payload)])
    return _finalize(h)