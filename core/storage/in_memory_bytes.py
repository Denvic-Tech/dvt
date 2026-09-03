import asyncio
from typing import Dict, Any

import orjson
from cachetools import TTLCache
from loguru import logger

from core.dump_engine import pick_engine_for, get_engine_by_name
from .base import Storage, T, OnItemRemoveCallback


class InMemoryBytesStorage(Storage[T]):
    """
    Реализация байтового хранилища в оперативной памяти с использованием TTL.
    """

    def __init__(
            self,
            maxsize: int = 1024,
            ttl: int = 3600,
            on_item_remove: OnItemRemoveCallback | None = None
    ):
        super().__init__(on_item_remove=on_item_remove)
        self._cache: TTLCache[str, bytes] = TTLCache(maxsize=maxsize, ttl=ttl)
        self._write_lock = asyncio.Lock()
        logger.info(f"In-memory bytes cache initialized with maxsize={maxsize}, ttl={ttl}s.")

    async def get(self, key: str) -> T:
        cached = self._cache.get(key)

        if cached is None:
            return None

        payload: Dict[str, Any] = orjson.loads(cached)

        engine_name = payload.get("cache_engine")
        data_hex = payload.get("data_hex")
        meta = payload.get("meta")

        if not engine_name or not data_hex:
            raise ValueError(f"Invalid cache payload structure for key '{key}': {payload}")

        engine = get_engine_by_name(engine_name)
        if engine is None:
            raise KeyError(f"Cache engine '{engine_name}' not found for key '{key}'")

        data_bytes = bytes.fromhex(data_hex)

        return engine.load(data_bytes, meta=meta)

    async def put(self, key: str, value: T):
        async with self._write_lock:
            cache_engine = pick_engine_for(value)
            data_bytes, meta = cache_engine.dump(value)

            payload = {
                "cache_engine": cache_engine.name,
                "data_hex": data_bytes.hex(),
                "meta": meta,
            }

            self._cache[key] = orjson.dumps(payload)

    async def has(self, key: str) -> bool:
        return key in self._cache

    async def remove(self, key: str, *keys: str) -> None:
        keys = (key,) + keys
        async with self._write_lock:
            for key in keys:
                if key in self._cache:
                    del self._cache[key]
                    self._handle_item_removal(key)

    async def clear(self):
        async with self._write_lock:
            keys = list(self._cache.keys())
            self._cache.clear()
            for key in keys:
                self._handle_item_removal(key)
        logger.info("In-memory bytes cache cleared.")

    async def keys(self) -> list[str]:
        return list(self._cache.keys())

    async def values(self) -> list[T]:
        return list(self._cache.values())

    async def items(self) -> list[tuple[str, T]]:
        return list(self._cache.items())

    async def dict(self) -> dict[str, T]:
        return dict(self._cache)
