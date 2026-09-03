import asyncio
from typing import Optional

from cachetools import TTLCache
from loguru import logger

from .base import Storage, OnItemRemoveCallback


class InMemoryBytesStorage(Storage[bytes]):
    """
    Простейшее TTL-хранилище, строго хранящее BYTES.
    Никакой (де)сериализации — это ответственность сервиса/клиента.
    """

    def __init__(
            self,
            *,
            maxsize: int = 1024,
            ttl: int = 3600,
            on_item_remove: Optional[OnItemRemoveCallback] = None,
    ):
        super().__init__(on_item_remove=on_item_remove)
        self._cache: TTLCache[str, bytes] = TTLCache(maxsize=maxsize, ttl=ttl)
        self._write_lock = asyncio.Lock()
        logger.info(f"InMemoryBytesStorage initialized (bytes-only) maxsize={maxsize}, ttl={ttl}s")

    # ---- CRUD ----

    async def get(self, key: str) -> Optional[bytes]:
        # TTLCache возвращает None, если ключ протух или отсутствует
        return self._cache.get(key)

    async def put(self, key: str, value: bytes) -> None:
        if not isinstance(value, (bytes, bytearray, memoryview)):
            raise TypeError("InMemoryBytesStorage.put expects bytes-like value")
        async with self._write_lock:
            self._cache[key] = bytes(value)

    async def remove(self, key: str, *keys: str) -> None:
        async with self._write_lock:
            for k in (key, *keys):
                if k in self._cache:
                    del self._cache[k]
                    self._handle_item_removal(k)

    async def has(self, key: str) -> bool:
        return key in self._cache

    async def clear(self) -> None:
        # вызовем on_item_remove для всех существующих ключей
        async with self._write_lock:
            keys = list(self._cache.keys())
            self._cache.clear()
            for k in keys:
                self._handle_item_removal(k)
        logger.info("InMemoryBytesStorage cleared")

    # ---- Introspection ----

    async def keys(self) -> list[str]:
        return list(self._cache.keys())

    async def values(self) -> list[bytes]:
        return list(self._cache.values())

    async def items(self) -> list[tuple[str, bytes]]:
        return list(self._cache.items())

    async def dict(self) -> dict[str, bytes]:
        return dict(self._cache)
