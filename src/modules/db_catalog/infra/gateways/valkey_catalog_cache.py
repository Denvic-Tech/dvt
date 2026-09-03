from __future__ import annotations

import asyncio
import hashlib
import secrets
import time
from dataclasses import dataclass

from redis.asyncio import Redis
from redis.exceptions import RedisError

from src.logger import logger
from src.modules.db_catalog.domain.entities import CatalogCacheEntry
from src.modules.db_catalog.domain.gateways import CatalogCacheGateway

from ..mappers import dump_cache_entry, load_cache_entry


@dataclass(slots=True)
class _MemoryValue:
    payload: bytes
    expires_at: float


class _MemoryCatalogCache:
    def __init__(self) -> None:
        self.values: dict[str, _MemoryValue] = {}
        self.epochs: dict[str, int] = {}
        self.locks: dict[str, tuple[str, float]] = {}
        self.guard = asyncio.Lock()

    async def get(self, key: str) -> bytes | None:
        async with self.guard:
            value = self.values.get(key)
            if value is None:
                return None
            if value.expires_at <= time.monotonic():
                self.values.pop(key, None)
                return None
            return value.payload

    async def set(self, key: str, payload: bytes, ttl_seconds: int) -> None:
        async with self.guard:
            self.values[key] = _MemoryValue(payload, time.monotonic() + ttl_seconds)

    async def get_epoch(self, key: str) -> int:
        async with self.guard:
            return self.epochs.get(key, 0)

    async def increment_epoch(self, key: str) -> int:
        async with self.guard:
            value = self.epochs.get(key, 0) + 1
            self.epochs[key] = value
            return value

    async def acquire(self, key: str, token: str, ttl_seconds: int) -> bool:
        async with self.guard:
            current = self.locks.get(key)
            now = time.monotonic()
            if current is not None and current[1] > now:
                return False
            self.locks[key] = (token, now + ttl_seconds)
            return True

    async def release(self, key: str, token: str) -> None:
        async with self.guard:
            current = self.locks.get(key)
            if current is not None and current[0] == token:
                self.locks.pop(key, None)

    async def locked(self, key: str) -> bool:
        async with self.guard:
            current = self.locks.get(key)
            if current is None:
                return False
            if current[1] <= time.monotonic():
                self.locks.pop(key, None)
                return False
            return True


_MEMORY_CACHE = _MemoryCatalogCache()


class ResilientValkeyCatalogCache(CatalogCacheGateway):
    _RELEASE_SCRIPT = """
    if redis.call('get', KEYS[1]) == ARGV[1] then
        return redis.call('del', KEYS[1])
    end
    return 0
    """

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    @staticmethod
    def _epoch_key(connection_id: str, revision: str) -> str:
        revision_hash = hashlib.sha256(revision.encode()).hexdigest()[:16]
        return f"dvt:db-catalog:epoch:v1:{connection_id}:{revision_hash}"

    @staticmethod
    def _lock_key(key: str) -> str:
        return f"{key}:flight"

    async def get_epoch(self, connection_id: str, revision: str) -> int:
        key = self._epoch_key(connection_id, revision)
        try:
            value = await self._redis.get(key)
            return int(value or 0)
        except (RedisError, OSError, TimeoutError):
            self._log_fallback("get_epoch")
            return await _MEMORY_CACHE.get_epoch(key)

    async def increment_epoch(self, connection_id: str, revision: str) -> int:
        key = self._epoch_key(connection_id, revision)
        try:
            value = await self._redis.incr(key)
            await self._redis.expire(key, 86400)
            return int(value)
        except (RedisError, OSError, TimeoutError):
            self._log_fallback("increment_epoch")
            return await _MEMORY_CACHE.increment_epoch(key)

    async def get(self, key: str) -> CatalogCacheEntry | None:
        try:
            payload = await self._redis.get(key)
        except (RedisError, OSError, TimeoutError):
            self._log_fallback("get")
            payload = await _MEMORY_CACHE.get(key)
        if payload is None:
            return None
        try:
            return load_cache_entry(payload)
        except (TypeError, ValueError, KeyError):
            logger.warning("Ignoring invalid DB catalog cache payload")
            return None

    async def set(self, key: str, entry: CatalogCacheEntry, ttl_seconds: int) -> None:
        payload = dump_cache_entry(entry)
        try:
            await self._redis.set(key, payload, ex=ttl_seconds)
        except (RedisError, OSError, TimeoutError):
            self._log_fallback("set")
            await _MEMORY_CACHE.set(key, payload, ttl_seconds)

    async def try_acquire(self, key: str, ttl_seconds: int) -> str | None:
        lock_key = self._lock_key(key)
        token = secrets.token_urlsafe(24)
        try:
            acquired = await self._redis.set(lock_key, token, nx=True, ex=ttl_seconds)
        except (RedisError, OSError, TimeoutError):
            self._log_fallback("try_acquire")
            acquired = await _MEMORY_CACHE.acquire(lock_key, token, ttl_seconds)
        return token if acquired else None

    async def release(self, key: str, token: str) -> None:
        lock_key = self._lock_key(key)
        try:
            await self._redis.eval(self._RELEASE_SCRIPT, 1, lock_key, token)
        except (RedisError, OSError, TimeoutError):
            self._log_fallback("release")
            await _MEMORY_CACHE.release(lock_key, token)

    async def wait_for_entry(self, key: str, timeout_seconds: float) -> CatalogCacheEntry | None:
        deadline = time.monotonic() + timeout_seconds
        lock_key = self._lock_key(key)
        while time.monotonic() < deadline:
            entry = await self.get(key)
            if entry is not None:
                return entry
            try:
                locked = bool(await self._redis.exists(lock_key))
            except (RedisError, OSError, TimeoutError):
                locked = await _MEMORY_CACHE.locked(lock_key)
            if not locked:
                return None
            await asyncio.sleep(0.05)
        return None

    @staticmethod
    def _log_fallback(operation: str) -> None:
        logger.warning("DB catalog Valkey operation failed; using local fallback: {}", operation)
