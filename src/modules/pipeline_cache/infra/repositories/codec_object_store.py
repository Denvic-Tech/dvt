from __future__ import annotations

from ...domain.gateways import CacheCodec
from ...domain.repositories import BlobStore


class CodecObjectStore[T]:
    def __init__(self, blob_store: BlobStore, codec: CacheCodec[T]) -> None:
        self._blob_store = blob_store
        self._codec = codec

    def encode(self, obj: T) -> bytes:
        return self._codec.dump(obj)

    def decode(self, payload: bytes) -> T:
        return self._codec.load(payload)

    async def put_encoded(self, key: str, payload: bytes, ttl_lifetime: int | None = None) -> None:
        await self._blob_store.put(key=key, payload=payload, ttl=ttl_lifetime)

    async def get_encoded(self, key: str) -> bytes | None:
        return await self._blob_store.get(key)

    async def compare_and_set_encoded(
        self,
        key: str,
        *,
        expected: bytes | None,
        payload: bytes,
        ttl_lifetime: int | None = None,
    ) -> bool:
        return await self._blob_store.compare_and_set(
            key,
            expected=expected,
            payload=payload,
            ttl=ttl_lifetime,
        )

    async def put(self, key: str, obj: T, ttl_lifetime: int | None = None) -> None:
        await self.put_encoded(key, self.encode(obj), ttl_lifetime)

    async def get(self, key: str) -> T | None:
        payload = await self.get_encoded(key)
        if payload is None:
            return None
        return self.decode(payload)

    async def get_many(self, keys) -> list[T | None]:
        payloads = await self._blob_store.get_many(keys)
        return [None if payload is None else self.decode(payload) for payload in payloads]

    async def has(self, key: str) -> bool:
        return await self._blob_store.has(key)

    async def has_many(self, keys) -> bool:
        return await self._blob_store.has_many(keys)

    async def keys(self, prefix: str) -> list[str]:
        return await self._blob_store.keys(prefix)

    async def remove(self, key: str, *keys: str) -> None:
        await self._blob_store.remove(key, *keys)

    async def clear(self) -> None:
        await self._blob_store.clear()

    async def close(self) -> None:
        await self._blob_store.close()
