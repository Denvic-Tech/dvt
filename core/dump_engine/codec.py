from __future__ import annotations

import dataclasses
import enum
import importlib
from typing import Any, Dict, Iterable, List, Tuple

import msgpack

from ._universal import decode_special, try_encode_special
from .registry import DumpMode
from .utils import get_engine_by_name, pick_engine_for

KIND_KEY = "__kind__"
PathSegment = Tuple[str, Any]
Path = Tuple[PathSegment, ...]


class DumpSerializationError(TypeError):
    """Raised when an object cannot be serialised by the dump engine."""

    def __init__(self, path: Path, obj_type: type[Any]) -> None:
        self.path = path
        self.obj_type = obj_type
        message = (
            f"Cannot serialise object of type "
            f"'{obj_type.__module__}.{obj_type.__qualname__}' "
            f"at path {_format_path(path)}"
        )
        super().__init__(message)


def dump(obj: Any, *, mode: DumpMode = "full") -> bytes:
    payload = _encode(obj, mode, ())
    return msgpack.packb(payload, use_bin_type=True)


def load(data: bytes | None) -> Any:
    if data is None:
        return None
    payload = msgpack.unpackb(data, raw=False)
    return _decode(payload)


def _encode(obj: Any, mode: DumpMode, path: Path) -> Any:
    # Check registered special types before the primitive fast-path. Several
    # numpy scalar classes intentionally subclass Python primitives
    # (np.float64 -> float, np.str_ -> str, np.bytes_ -> bytes); handling
    # primitives first would silently discard their dtype on round-trip.
    special = try_encode_special(obj)
    if special:
        type_name, value = special
        return {
            KIND_KEY: "special",
            "type": type_name,
            "value": value,
        }

    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj

    if isinstance(obj, (bytes, bytearray, memoryview)):
        return bytes(obj)

    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        cls = obj.__class__
        fields_payload = {
            field.name: _encode(getattr(obj, field.name), mode, path + (("attr", field.name),))
            for field in dataclasses.fields(obj)
        }
        return {
            KIND_KEY: "dataclass",
            "module": cls.__module__,
            "qualname": cls.__qualname__,
            "fields": fields_payload,
        }

    if isinstance(obj, enum.Enum):
        enum_cls = obj.__class__
        return {
            KIND_KEY: "enum",
            "module": enum_cls.__module__,
            "qualname": enum_cls.__qualname__,
            "name": obj.name,
        }

    if isinstance(obj, list):
        return {
            KIND_KEY: "list",
            "items": [_encode(item, mode, path + (("index", idx),)) for idx, item in enumerate(obj)],
        }

    if isinstance(obj, tuple):
        return {
            KIND_KEY: "tuple",
            "items": [_encode(item, mode, path + (("index", idx),)) for idx, item in enumerate(obj)],
        }

    if isinstance(obj, set):
        return {
            KIND_KEY: "set",
            "items": [_encode(item, mode, path + (("set", idx),)) for idx, item in enumerate(obj)],
        }

    if isinstance(obj, frozenset):
        return {
            KIND_KEY: "frozenset",
            "items": [_encode(item, mode, path + (("set", idx),)) for idx, item in enumerate(obj)],
        }

    if isinstance(obj, dict):
        items: List[Any] = []
        for index, (key, value) in enumerate(obj.items()):
            encoded_key = _encode(key, mode, path + (("dict-key", key),))
            encoded_value = _encode(value, mode, path + (("key", key),))
            items.append([encoded_key, encoded_value])
        return {
            KIND_KEY: "dict",
            "items": items,
        }

    try:
        engine = pick_engine_for(obj, mode)
    except ValueError as exc:  # pragma: no cover - defensive, enriched below
        raise DumpSerializationError(path, type(obj)) from exc

    data, meta = engine.dump(obj)
    payload: Dict[str, Any] = {
        KIND_KEY: "engine",
        "name": engine.name,
        "data": data,
    }

    if meta is not None:
        payload["meta"] = _encode(meta, "full", path + (("meta", engine.name),))

    return payload


def _decode(payload: Any) -> Any:
    if payload is None or isinstance(payload, (bool, int, float, str, bytes)):
        return payload

    if isinstance(payload, list):
        return [_decode(item) for item in payload]

    if not isinstance(payload, dict):
        return payload

    kind = payload.get(KIND_KEY)
    if kind is None:
        return {key: _decode(value) for key, value in payload.items()}

    if kind == "list":
        return [_decode(item) for item in payload["items"]]

    if kind == "tuple":
        return tuple(_decode(item) for item in payload["items"])

    if kind == "set":
        return set(_decode(item) for item in payload["items"])

    if kind == "frozenset":
        return frozenset(_decode(item) for item in payload["items"])

    if kind == "dict":
        return {key: value for key, value in _decode_pairs(payload["items"])}

    if kind == "dataclass":
        cls = _import_qualname(payload["module"], payload["qualname"])
        fields_payload = {name: _decode(value) for name, value in payload["fields"].items()}
        return cls(**fields_payload)

    if kind == "enum":
        enum_cls = _import_qualname(payload["module"], payload["qualname"])
        return enum_cls[payload["name"]]

    if kind == "special":
        return decode_special(payload["type"], payload.get("value"))

    if kind == "engine":
        engine_name = payload["name"]
        engine = get_engine_by_name(engine_name)
        if engine is None:
            raise ValueError(f"Unknown cache engine '{engine_name}'.")
        meta_payload = payload.get("meta")
        meta = _decode(meta_payload) if meta_payload is not None else None
        return engine.load(payload["data"], meta=meta)

    raise ValueError(f"Unsupported payload kind '{kind}'.")


def _decode_pairs(items: Iterable[Any]) -> Iterable[Tuple[Any, Any]]:
    for pair in items:
        if not isinstance(pair, list) or len(pair) != 2:
            raise ValueError("Malformed dictionary payload encountered during deserialisation.")
        yield _decode(pair[0]), _decode(pair[1])


def _import_qualname(module_name: str, qualname: str) -> Any:
    module = importlib.import_module(module_name)
    obj = module
    for part in qualname.split("."):
        obj = getattr(obj, part)
    return obj


def _format_path(path: Path) -> str:
    if not path:
        return "<root>"

    result = "<root>"
    for kind, value in path:
        if kind == "attr":
            result += f".{value}"
        elif kind in {"index", "set"}:
            result += f"[{value}]"
        elif kind == "meta":
            result += f".<meta:{value}>"
        else:
            result += f"[{value!r}]"
    return result
