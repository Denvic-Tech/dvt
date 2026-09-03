from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from ...domain.policies import resolve_ttl
from ...domain.repositories import BlobStore


@dataclass
class _MemoryRecord:
    value: bytes
    expires_at: float


class InMemoryBlobStore(BlobStore):
    def __init__(self, *, default_ttl: int) -> None:
        self._default_ttl = default_ttl
        self._records: dict[str, _MemoryRecord] = {}
        self._lock = asyncio.Lock()

    async def put(self, key: str, payload: bytes, ttl: int | None = None) -> None:
        resolved_ttl = resolve_ttl(ttl, self._default_ttl)
        async with self._lock:
            self._records[key] = _MemoryRecord(value=bytes(payload), expires_at=time.monotonic() + resolved_ttl)

    async def get(self, key: str) -> bytes | None:
        async with self._lock:
            self._purge_expired()
            record = self._records.get(key)
            return None if record is None else bytes(record.value)

    async def compare_and_set(
        self,
        key: str,
        *,
        expected: bytes | None,
        payload: bytes,
        ttl: int | None = None,
    ) -> bool:
        resolved_ttl = resolve_ttl(ttl, self._default_ttl)
        async with self._lock:
            self._purge_expired()
            record = self._records.get(key)
            current = None if record is None else record.value
            if current != expected:
                return False
            self._records[key] = _MemoryRecord(
                value=bytes(payload),
                expires_at=time.monotonic() + resolved_ttl,
            )
            return True

    async def get_many(self, keys) -> list[bytes | None]:
        async with self._lock:
            self._purge_expired()
            return [
                None if (record := self._records.get(key)) is None else bytes(record.value)
                for key in keys
            ]

    async def has(self, key: str) -> bool:
        async with self._lock:
            self._purge_expired()
            return key in self._records

    async def has_many(self, keys) -> bool:
        async with self._lock:
            self._purge_expired()
            return all(key in self._records for key in keys)

    async def keys(self, prefix: str) -> list[str]:
        async with self._lock:
            self._purge_expired()
            return sorted(key for key in self._records if key.startswith(prefix))

    async def remove(self, key: str, *keys: str) -> None:
        async with self._lock:
            self._purge_expired()
            for item in (key, *keys):
                self._records.pop(item, None)

    async def clear(self) -> None:
        async with self._lock:
            self._records.clear()

    async def close(self) -> None:
        return None

    def _purge_expired(self) -> None:
        now = time.monotonic()
        expired_keys = [key for key, record in self._records.items() if record.expires_at <= now]
        for key in expired_keys:
            self._records.pop(key, None)
