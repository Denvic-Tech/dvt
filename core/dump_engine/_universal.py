from __future__ import annotations

import importlib
import inspect
from datetime import datetime, date, time
from decimal import Decimal
from types import ModuleType
from typing import Any, Callable, Dict, Optional, Tuple
from uuid import UUID

import numpy as np


def _encode_numpy_scalar(value: np.generic) -> dict[str, Any]:
    return {
        "dtype": value.dtype.str,
        "data": value.tobytes(),
    }


def _decode_numpy_scalar(payload: dict[str, Any]) -> np.generic:
    dtype = np.dtype(payload["dtype"])
    return np.frombuffer(payload["data"], dtype=dtype, count=1)[0]


_NUMPY_SCALAR_TYPES = (
    np.bool_,
    np.integer,
    np.floating,
    np.complexfloating,
    np.datetime64,
    np.timedelta64,
    np.str_,
    np.bytes_,
)


_ENCODERS: Dict[str, Tuple[Tuple[type, ...], Callable[[Any], Any], Callable[[Any], Any]]] = {
    "datetime": ((datetime,), lambda value: value.isoformat(), lambda raw: datetime.fromisoformat(raw)),
    "date": ((date,), lambda value: value.isoformat(), lambda raw: date.fromisoformat(raw)),
    "time": ((time,), lambda value: value.isoformat(), lambda raw: time.fromisoformat(raw)),
    "decimal": ((Decimal,), lambda value: str(value), lambda raw: Decimal(raw)),
    "uuid": ((UUID,), lambda value: str(value), lambda raw: UUID(raw)),
    "numpy_scalar": (_NUMPY_SCALAR_TYPES, _encode_numpy_scalar, _decode_numpy_scalar),
    "ellipsis": ((type(Ellipsis),), lambda value: "__ellipsis__", lambda raw: Ellipsis),
}


def try_encode_special(value: Any) -> Optional[Tuple[str, Any]]:
    for type_name, (classes, encoder, _) in _ENCODERS.items():
        if isinstance(value, classes):
            return type_name, encoder(value)

    if inspect.isclass(value):
        return "type", f"{value.__module__}.{value.__qualname__}"

    if isinstance(value, ModuleType):
        return "module", value.__name__

    return None


def decode_special(type_name: str, payload: Any) -> Any:
    if type_name in _ENCODERS:
        _, _, decoder = _ENCODERS[type_name]
        return decoder(payload)

    if type_name == "type":
        return _import_object(payload)

    if type_name == "module":
        return importlib.import_module(payload)

    raise ValueError(f"Unsupported special type '{type_name}'.")


def _import_object(path: str) -> Any:
    module_path, _, qualname = path.rpartition(".")
    if not module_path or not qualname:
        raise ImportError(f"Unable to import object from '{path}'")

    module = importlib.import_module(module_path)
    obj = module
    for part in qualname.split("."):
        obj = getattr(obj, part)
    return obj
