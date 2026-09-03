from __future__ import annotations

from typing import Dict, Iterable, List, Literal

from ._dask import DaskMetaCacheEngine
from ._pandas import UniversalPyArrowCacheEngine
from ._pydantic import PydanticModelCacheEngine
from ._sqlalchemy import SAEngineCacheEngine
from .protocol import CacheEngine

_dask_meta_engine = DaskMetaCacheEngine()
_pyarrow_engine = UniversalPyArrowCacheEngine()
_pydantic_engine = PydanticModelCacheEngine()
_sa_engine = SAEngineCacheEngine()


DumpMode = Literal["full", "meta"]


_ENGINE_REGISTRY: Dict[DumpMode, List[CacheEngine]] = {
    "full": [
        _pyarrow_engine,
        _pydantic_engine,
        _sa_engine,
    ],
    "meta": [
        _dask_meta_engine,
        _pyarrow_engine,
        _pydantic_engine,
        _sa_engine,
    ],
}


def get_engine_registry(mode: DumpMode = "full") -> List[CacheEngine]:
    return _ENGINE_REGISTRY[mode]


def iter_all_engines() -> Iterable[CacheEngine]:
    seen: set[str] = set()
    for engines in _ENGINE_REGISTRY.values():
        for engine in engines:
            if engine.name in seen:
                continue
            seen.add(engine.name)
            yield engine


_ENGINE_BY_NAME: Dict[str, CacheEngine] = {engine.name: engine for engine in iter_all_engines()}


def get_engine_by_name_cached(name: str) -> CacheEngine | None:
    return _ENGINE_BY_NAME.get(name)
