from __future__ import annotations

import asyncio
import threading
import time
import weakref
from dataclasses import dataclass

from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError, RedisError

from ...domain.value_objects import RedisStoreSettings


@dataclass
class _LoopRedisClient:
    client: Redis
    last_used_at: float


class RedisClientPool:
    def __init__(self, settings: RedisStoreSettings) -> None:
        self._settings = settings
        self._client_entry: _LoopRedisClient | None = None
        self._clients: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, _LoopRedisClient] = (
            weakref.WeakKeyDictionary()
        )
        self._state_lock = threading.RLock()
        self._last_cleanup_at = 0.0

    async def get_client(self) -> Redis:
        await self._cleanup_stale_clients()
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        now = time.monotonic()
        if loop is not None:
            with self._state_lock:
                entry = self._clients.get(loop)
            if entry is not None:
                entry.last_used_at = now
                return entry.client
        else:
            with self._state_lock:
                entry = self._client_entry
            if entry is not None:
                entry.last_used_at = now
                return entry.client

        try:
            client = Redis.from_url(self._settings.redis_url, decode_responses=False)
        except RedisConnectionError as exc:  # pragma: no cover - delegated to redis client
            raise ConnectionError(f"Could not connect to Redis: {exc}") from exc
        except RedisError as exc:  # pragma: no cover - delegated to redis client
            raise ConnectionError(f"Redis error: {exc}") from exc

        entry = _LoopRedisClient(client=client, last_used_at=now)
        with self._state_lock:
            if loop is not None:
                self._clients[loop] = entry
            else:
                self._client_entry = entry
        return client

    async def close(self) -> None:
        with self._state_lock:
            clients_to_close = [
                (loop, entry.client)
                for loop, entry in self._clients.items()
            ]
            self._clients.clear()
            loopless_client = None
            if self._client_entry is not None:
                loopless_client = self._client_entry.client
                self._client_entry = None

        for owner_loop, client in clients_to_close:
            await self._close_on_owner_loop(owner_loop, client)
        if loopless_client is not None:
            try:
                await loopless_client.aclose()
            except Exception:
                pass

    async def _cleanup_stale_clients(self) -> None:
        now = time.monotonic()
        if now - self._last_cleanup_at < self._settings.idle_sweep_interval_sec:
            return
        self._last_cleanup_at = now

        ttl = self._settings.idle_connection_ttl_sec
        stale_clients: list[tuple[asyncio.AbstractEventLoop, Redis]] = []
        stale_loops: list[asyncio.AbstractEventLoop] = []

        with self._state_lock:
            client_items = list(self._clients.items())
        for loop, entry in client_items:
            if loop.is_closed() or (now - entry.last_used_at >= ttl):
                stale_loops.append(loop)

        with self._state_lock:
            for loop in stale_loops:
                entry = self._clients.pop(loop, None)
                if entry is not None:
                    stale_clients.append((loop, entry.client))

            loopless_client = None
            if self._client_entry is not None and (now - self._client_entry.last_used_at >= ttl):
                loopless_client = self._client_entry.client
                self._client_entry = None

        for owner_loop, client in stale_clients:
            await self._close_on_owner_loop(owner_loop, client)
        if loopless_client is not None:
            try:
                await loopless_client.aclose()
            except Exception:
                pass

    @staticmethod
    async def _close_on_owner_loop(owner_loop: asyncio.AbstractEventLoop, client: Redis) -> None:
        """Close an asyncio Redis client only on the loop that owns its transports."""
        if owner_loop.is_closed():
            # The transport can no longer be driven safely. Dropping our strong
            # reference is preferable to touching a Proactor transport from a
            # foreign/closed loop and raising InvalidStateError.
            return
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:  # pragma: no cover - called from async methods
            current_loop = None

        try:
            if owner_loop is current_loop:
                await client.aclose()
                return
            if not owner_loop.is_running():
                return
            future = asyncio.run_coroutine_threadsafe(client.aclose(), owner_loop)
            await asyncio.wrap_future(future)
        except Exception:
            # Cache connection cleanup is best effort and must never make the
            # caller's pipeline/cache operation fail.
            return
