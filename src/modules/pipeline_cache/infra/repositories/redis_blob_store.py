from __future__ import annotations

from ...domain.policies import resolve_ttl
from ...domain.repositories import BlobStore
from ...domain.value_objects import RedisStoreSettings
from ._redis_client import RedisClientPool


class RedisBlobStore(BlobStore):
    _COMPARE_AND_SET_SCRIPT = """
local current = redis.call('GET', KEYS[1])
local expects_missing = ARGV[1] == '1'
if expects_missing then
    if current then
        return 0
    end
else
    if not current or current ~= ARGV[2] then
        return 0
    end
end

local payload = ARGV[3]
local ttl = tonumber(ARGV[4])
if ttl and ttl > 0 then
    redis.call('SET', KEYS[1], payload, 'EX', ttl)
else
    redis.call('SET', KEYS[1], payload)
end
return 1
"""

    def __init__(self, settings: RedisStoreSettings) -> None:
        self._settings = settings
        self._clients = RedisClientPool(settings)

    async def put(self, key: str, payload: bytes, ttl: int | None = None) -> None:
        client = await self._clients.get_client()
        await client.set(self._with_prefix(key), payload, ex=resolve_ttl(ttl, self._settings.default_ttl))

    async def get(self, key: str) -> bytes | None:
        client = await self._clients.get_client()
        return await client.get(self._with_prefix(key))

    async def compare_and_set(
        self,
        key: str,
        *,
        expected: bytes | None,
        payload: bytes,
        ttl: int | None = None,
    ) -> bool:
        client = await self._clients.get_client()
        resolved_ttl = resolve_ttl(ttl, self._settings.default_ttl)
        result = await client.eval(
            self._COMPARE_AND_SET_SCRIPT,
            1,
            self._with_prefix(key),
            b"1" if expected is None else b"0",
            b"" if expected is None else expected,
            payload,
            str(resolved_ttl).encode("ascii"),
        )
        return bool(result)

    async def get_many(self, keys) -> list[bytes | None]:
        normalized = [self._with_prefix(key) for key in keys]
        if not normalized:
            return []
        client = await self._clients.get_client()
        return list(await client.mget(normalized))

    async def has(self, key: str) -> bool:
        client = await self._clients.get_client()
        return bool(await client.exists(self._with_prefix(key)))

    async def has_many(self, keys) -> bool:
        normalized = [self._with_prefix(key) for key in keys]
        if not normalized:
            return True
        client = await self._clients.get_client()
        return int(await client.exists(*normalized)) == len(normalized)

    async def keys(self, prefix: str) -> list[str]:
        client = await self._clients.get_client()
        physical_prefix = self._with_prefix(prefix)
        storage_prefix = self._settings.key_prefix.rstrip("/")
        logical_keys: list[str] = []
        async for key in client.scan_iter(match=f"{physical_prefix}*"):
            raw = key.decode("utf-8") if isinstance(key, (bytes, bytearray)) else str(key)
            if storage_prefix and raw.startswith(f"{storage_prefix}/"):
                raw = raw[len(storage_prefix) + 1:]
            logical_keys.append(raw)
        return sorted(logical_keys)

    async def remove(self, key: str, *keys: str) -> None:
        client = await self._clients.get_client()
        all_keys = [self._with_prefix(key)] + [self._with_prefix(item) for item in keys]
        await client.delete(*all_keys)

    async def clear(self) -> None:
        client = await self._clients.get_client()
        if not self._settings.key_prefix:
            await client.flushdb()
            return

        prefix = f"{self._settings.key_prefix.rstrip('/')}/"
        keys_to_delete: list[bytes] = []
        async for key in client.scan_iter(match=f"{prefix}*"):
            keys_to_delete.append(key)
            if len(keys_to_delete) >= 500:
                await client.delete(*keys_to_delete)
                keys_to_delete.clear()
        if keys_to_delete:
            await client.delete(*keys_to_delete)

    async def close(self) -> None:
        await self._clients.close()

    def _with_prefix(self, key: str) -> str:
        if not self._settings.key_prefix:
            return key
        normalized_key = key.lstrip("/")
        prefix = self._settings.key_prefix.rstrip("/")
        prefixed = f"{prefix}/{normalized_key}"
        if key.startswith(f"{prefix}/"):
            return key
        return prefixed
