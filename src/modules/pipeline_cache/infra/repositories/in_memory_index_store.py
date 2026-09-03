from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, fields
from typing import Callable

from ...domain.keys import IndexKeyBase, camel_to_snake, index_key_from_str
from ...domain.policies import resolve_ttl
from ...domain.repositories import IndexStore, K, V


@dataclass
class _MemoryRecord:
    payload: bytes
    expires_at: float


class InMemoryIndexStore(IndexStore[K, V]):
    def __init__(
        self,
        serializer: Callable[[V], bytes],
        deserializer: Callable[[bytes], V],
        *,
        default_ttl: int,
        separator: str = ":",
    ) -> None:
        self.serializer = serializer
        self.deserializer = deserializer
        self._default_ttl = default_ttl
        self._separator = separator
        self._records: dict[str, _MemoryRecord] = {}
        self._lock = asyncio.Lock()

    async def put(self, index_key: K, value: V, ttl: int | None = None) -> None:
        resolved_ttl = resolve_ttl(ttl, self._default_ttl)
        key = index_key.to_str(sep=self._separator, ensure_full=True)
        payload = self.serializer(value)
        async with self._lock:
            self._records[key] = _MemoryRecord(payload=payload, expires_at=time.monotonic() + resolved_ttl)

    async def get(self, store_key: str) -> V | None:
        async with self._lock:
            self._purge_expired()
            record = self._records.get(store_key)
            return None if record is None else self.deserializer(record.payload)

    async def contains(self, index_key: K) -> bool:
        async with self._lock:
            self._purge_expired()
            if self._is_full_key(index_key):
                return index_key.to_str(sep=self._separator, ensure_full=True) in self._records
            prefix = self._prefix(index_key)
            return any(stored_key.startswith(prefix + self._separator) for stored_key in self._records)

    async def query(self, index_key: K) -> list[V]:
        async with self._lock:
            self._purge_expired()
            prefix = self._prefix(index_key)
            is_full_key = self._is_full_key(index_key)
            results: list[V] = []

            for stored_key in sorted(self._records):
                if is_full_key:
                    if stored_key != prefix:
                        continue
                elif not stored_key.startswith(prefix + self._separator):
                    continue
                results.append(self.deserializer(self._records[stored_key].payload))
            return results

    async def keys(self, key_type: type[K]) -> list[K]:
        async with self._lock:
            self._purge_expired()
            return [
                index_key_from_str(key_type, stored_key, sep=self._separator)
                for stored_key in sorted(self._records)
                if self._matches_key_type(stored_key, key_type)
            ]

    async def remove(self, index_key: K) -> None:
        async with self._lock:
            self._purge_expired()
            prefix = self._prefix(index_key)
            is_full_key = self._is_full_key(index_key)
            if is_full_key:
                self._records.pop(prefix, None)
                return
            keys_to_delete = [stored_key for stored_key in self._records if stored_key.startswith(prefix + self._separator)]
            for key in keys_to_delete:
                self._records.pop(key, None)

    async def clear(self) -> None:
        async with self._lock:
            self._records.clear()

    async def reindex(self, entries, *, clear_first: bool = True) -> int:
        if clear_first:
            await self.clear()
        count = 0
        for index_key, value in entries:
            await self.put(index_key, value)
            count += 1
        return count

    async def close(self) -> None:
        return None

    def _prefix(self, index_key: K) -> str:
        return index_key.to_str(sep=self._separator, ensure_full=self._is_full_key(index_key))

    @staticmethod
    def _is_full_key(index_key: K) -> bool:
        segments = index_key.to_segments(ensure_full=False)
        total_fields = sum(1 for field in fields(index_key) if field.init)
        value_segments = max(0, len(segments) - 1)
        return value_segments == total_fields

    def _purge_expired(self) -> None:
        now = time.monotonic()
        expired_keys = [key for key, record in self._records.items() if record.expires_at <= now]
        for key in expired_keys:
            self._records.pop(key, None)

    def _matches_key_type(self, stored_key: str, key_type: type[K]) -> bool:
        expected_key_name = camel_to_snake(key_type.__name__)
        actual_key_name, _, _ = stored_key.partition(self._separator)
        return actual_key_name == expected_key_name
