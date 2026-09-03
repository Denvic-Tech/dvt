from __future__ import annotations

from collections.abc import Callable
from dataclasses import fields

from ...domain.keys import camel_to_snake, index_key_from_str
from ...domain.policies import resolve_ttl
from ...domain.repositories import IndexStore, K, V
from ...domain.value_objects import RedisStoreSettings
from ._redis_client import RedisClientPool


def _strip_suffix(value: str, suffix: str) -> str:
    if value.endswith(suffix):
        return value[:-len(suffix)]
    return value


class RedisIndexStore(IndexStore[K, V]):
    def __init__(
        self,
        serializer: Callable[[V], bytes],
        deserializer: Callable[[bytes], V],
        settings: RedisStoreSettings,
    ) -> None:
        self.serializer = serializer
        self.deserializer = deserializer
        self._settings = settings
        self._clients = RedisClientPool(settings)
        self._separator = settings.separator

    async def put(self, index_key: K, value: V, ttl: int | None = None) -> None:
        client = await self._clients.get_client()
        key = self._build_index_key(index_key, ensure_full=True)
        payload = self.serializer(value)
        await client.set(key, payload, ex=resolve_ttl(ttl, self._settings.default_ttl))

    async def get(self, store_key: str) -> V | None:
        client = await self._clients.get_client()
        payload = await client.get(self._with_prefix(store_key))
        if payload is None:
            return None
        return self.deserializer(payload)

    async def contains(self, index_key: K) -> bool:
        client = await self._clients.get_client()
        if self._is_full_key(index_key):
            return bool(await client.exists(self._build_index_key(index_key, ensure_full=True)))

        prefix_key = self._build_index_key(index_key, ensure_full=False)
        pattern = f"{prefix_key}{self._separator}*"
        async for _ in client.scan_iter(match=pattern, count=100):
            return True
        return False

    async def query(self, index_key: K) -> list[V]:
        client = await self._clients.get_client()
        if self._is_full_key(index_key):
            payload = await client.get(self._build_index_key(index_key, ensure_full=True))
            return [self.deserializer(payload)] if payload is not None else []

        prefix_key = self._build_index_key(index_key, ensure_full=False)
        pattern = f"{prefix_key}{self._separator}*"
        keys: list[bytes] = []
        async for key in client.scan_iter(match=pattern):
            keys.append(key)
        if not keys:
            return []

        values = await client.mget(keys)
        results: list[V] = []
        for payload in values:
            if payload is None:
                continue
            results.append(self.deserializer(payload))
        return results

    async def keys(self, key_type: type[K]) -> list[K]:
        client = await self._clients.get_client()
        pattern = "*"
        if self._settings.key_prefix:
            prefix = f"{self._normalize_prefix()}{self._separator}"
            pattern = f"{prefix}*"

        result: list[K] = []
        async for key in client.scan_iter(match=pattern):
            key_str = key.decode("utf-8") if isinstance(key, (bytes, bytearray)) else str(key)
            key_str = self._strip_prefix(key_str)
            if not self._matches_key_type(key_str, key_type):
                continue
            result.append(index_key_from_str(key_type, key_str, sep=self._separator))
        return result

    async def remove(self, index_key: K) -> None:
        client = await self._clients.get_client()
        if self._is_full_key(index_key):
            await client.delete(self._build_index_key(index_key, ensure_full=True))
            return

        prefix_key = self._build_index_key(index_key, ensure_full=False)
        pattern = f"{prefix_key}{self._separator}*"
        keys_to_delete: list[bytes] = []
        async for key in client.scan_iter(match=pattern):
            keys_to_delete.append(key)
            if len(keys_to_delete) >= 500:
                await client.delete(*keys_to_delete)
                keys_to_delete.clear()
        if keys_to_delete:
            await client.delete(*keys_to_delete)

    async def clear(self) -> None:
        client = await self._clients.get_client()
        if not self._settings.key_prefix:
            await client.flushdb()
            return

        prefix = f"{self._normalize_prefix()}{self._separator}"
        keys_to_delete: list[bytes] = []
        async for key in client.scan_iter(match=f"{prefix}*"):
            keys_to_delete.append(key)
            if len(keys_to_delete) >= 500:
                await client.delete(*keys_to_delete)
                keys_to_delete.clear()
        if keys_to_delete:
            await client.delete(*keys_to_delete)

    async def reindex(self, entries, *, clear_first: bool = True) -> int:
        if clear_first:
            await self.clear()
        count = 0
        for index_key, value in entries:
            await self.put(index_key, value)
            count += 1
        return count

    async def close(self) -> None:
        await self._clients.close()

    def _normalize_prefix(self) -> str:
        if not self._settings.key_prefix:
            return ""
        return _strip_suffix(self._settings.key_prefix, self._separator)

    def _with_prefix(self, key: str) -> str:
        prefix = self._normalize_prefix()
        if not prefix:
            return key
        if key.startswith(f"{prefix}{self._separator}"):
            return key
        return f"{prefix}{self._separator}{key}"

    def _build_index_key(self, index_key: K, *, ensure_full: bool) -> str:
        base_key = index_key.to_str(sep=self._separator, ensure_full=ensure_full)
        return self._with_prefix(base_key)

    @staticmethod
    def _is_full_key(index_key: K) -> bool:
        segments = index_key.to_segments(ensure_full=False)
        total_fields = sum(1 for field in fields(index_key) if field.init)
        value_segments = max(0, len(segments) - 1)
        return value_segments == total_fields

    def _strip_prefix(self, key: str) -> str:
        prefix = self._normalize_prefix()
        if not prefix:
            return key
        prefix_with_sep = f"{prefix}{self._separator}"
        if key.startswith(prefix_with_sep):
            return key[len(prefix_with_sep):]
        return key

    def _matches_key_type(self, key: str, key_type: type[K]) -> bool:
        expected_key_name = camel_to_snake(key_type.__name__)
        actual_key_name, _, _ = key.partition(self._separator)
        return actual_key_name == expected_key_name
