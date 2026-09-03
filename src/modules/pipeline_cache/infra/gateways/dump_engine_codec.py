from __future__ import annotations

from typing import Any

from core import dump_engine

from ...domain.gateways import CacheCodec


class DumpEngineCodec(CacheCodec[Any]):
    def __init__(self, *, dump_kwargs: dict[str, Any] | None = None) -> None:
        self._dump_kwargs = dict(dump_kwargs or {})

    def dump(self, value: Any) -> bytes:
        return dump_engine.dump(value, **self._dump_kwargs)

    def load(self, payload: bytes) -> Any:
        return dump_engine.load(payload)
