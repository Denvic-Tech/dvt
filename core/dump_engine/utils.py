from __future__ import annotations

from typing import Any, Optional

from .protocol import CacheEngine
from .registry import DumpMode, get_engine_registry, get_engine_by_name_cached


def get_engine_by_name(name: str) -> Optional[CacheEngine]:
    return get_engine_by_name_cached(name)


def pick_engine_for(obj: Any, mode: DumpMode = "full") -> CacheEngine:
    registry = get_engine_registry(mode)
    for engine in registry:
        if engine.can_handle(obj):
            return engine

    if mode == "meta":
        for engine in get_engine_registry(mode="full"):
            if engine.can_handle(obj):
                return engine

    raise ValueError(f"No suitable cache engine found for the object '{type(obj)}' in mode '{mode}'.")
