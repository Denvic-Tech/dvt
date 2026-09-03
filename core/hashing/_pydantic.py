from typing import Any, Type

import pydantic as pyd

from .hasher import _new_hasher
from .utils import _update_many, _to_bytes_fast, _finalize


def _get_pydantic_object_hash(obj: pyd.BaseModel | Type[pyd.BaseModel]) -> bytes:
    hasher = _new_hasher()

    _update_many(hasher, [
        _to_bytes_fast(obj.__class__.__module__),
        b":",
        _to_bytes_fast(obj.__class__.__qualname__),
        b"|",
    ])

    _update_many(hasher, [_to_bytes_fast(obj.model_dump())])
    return _finalize(hasher)


def _get_pydantic_model_hash(obj: Type[pyd.BaseModel]) -> bytes:
    hasher = _new_hasher()

    _update_many(hasher, [
        _to_bytes_fast(obj.__module__),
        b":",
        _to_bytes_fast(obj.__qualname__),
        b"|",
    ])

    return _finalize(hasher)
