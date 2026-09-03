import asyncio

from cachetools import TTLCache
from loguru import logger

from .base import Storage, T, OnItemRemoveCallback


class InMemoryStorage(Storage[T]):
    """
    Реализация хранилища кеша в оперативной памяти с использованием TTL.
    """

    def __init__(
            self,
            maxsize: int = 1024,
            ttl: int = 3600,
            on_item_remove: OnItemRemoveCallback | None = None
    ):
        super().__init__(on_item_remove=on_item_remove)

        self._data_cache: TTLCache = TTLCache(maxsize=maxsize, ttl=ttl)
        self._write_lock = asyncio.Lock()
        logger.info(f"In-memory cache initialized with maxsize={maxsize}, ttl={ttl}s.")

    async def get(self, key: str):
        return self._data_cache.get(key)

    async def put(self, key: str, value: T):
        async with self._write_lock:
            self._data_cache[key] = value

    async def remove(self, key: str, *keys: str) -> None:
        keys = (key,) + keys
        async with self._write_lock:
            for key in keys:
                if key in self._data_cache:
                    del self._data_cache[key]
                    self._handle_item_removal(key)

    async def has(self, key: str) -> bool:
        return key in self._data_cache

    async def clear(self):
        async with self._write_lock:
            keys = list(self._data_cache.keys())
            self._data_cache.clear()
            for key in keys:
                self._handle_item_removal(key)
        logger.info("In-memory cache cleared.")

    async def keys(self) -> list[str]:
        return list(self._data_cache.keys())

    async def values(self) -> list[T]:
        return list(self._data_cache.values())

    async def items(self) -> list[tuple[str, T]]:
        return list(self._data_cache.items())

    async def dict(self) -> dict[str, T]:
        return dict(self._data_cache)
