from __future__ import annotations

import asyncio

from cachetools import TTLCache

from ..domain.gateways import AppSettingsCache
from ..domain.value_objects import AppSettingsValue


class InMemoryAppSettingsCache[SettingsT: AppSettingsValue](AppSettingsCache,):
    _CACHE_KEY = "settings"

    def __init__(self, ttl: int = 60) -> None:
        self._cache: TTLCache[str, SettingsT] = TTLCache(
            maxsize=1,
            ttl=ttl,
        )
        self._lock = asyncio.Lock()

    async def get(self) -> SettingsT | None:
        async with self._lock:
            return self._cache.get(self._CACHE_KEY)

    async def set(self, settings: SettingsT) -> None:
        async with self._lock:
            self._cache[self._CACHE_KEY] = settings

    async def invalidate(self) -> None:
        async with self._lock:
            self._cache.pop(self._CACHE_KEY, None)