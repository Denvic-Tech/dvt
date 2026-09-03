from datetime import UTC, datetime

import orjson
from redis import asyncio as redis

from ...domain.entities import NestedWaitReservation
from ...domain.gateways import NestedWaitReservationGateway

_RESERVE_SCRIPT = """
local key = KEYS[1]
local parent = ARGV[1]
local payload = ARGV[2]
local max_waiters = tonumber(ARGV[3])
if redis.call('HEXISTS', key, parent) == 1 then
    return 1
end
if redis.call('HLEN', key) >= max_waiters then
    return 0
end
redis.call('HSET', key, parent, payload)
return 1
"""

_REBALANCE_SCRIPT = """
local key = KEYS[1]
local max_waiters = tonumber(ARGV[1])
local entries = redis.call('HGETALL', key)
local reservations = {}
for i = 1, #entries, 2 do
    local parent = entries[i]
    local payload = entries[i + 1]
    local decoded = cjson.decode(payload)
    table.insert(reservations, {
        parent = parent,
        payload = payload,
        created_at = decoded['created_at'] or '',
    })
end
if #reservations <= max_waiters then
    return {}
end
table.sort(reservations, function(a, b)
    if a.created_at == b.created_at then
        return a.parent > b.parent
    end
    return a.created_at > b.created_at
end)
local removed = {}
for i = 1, (#reservations - max_waiters) do
    redis.call('HDEL', key, reservations[i].parent)
    table.insert(removed, reservations[i].payload)
end
return removed
"""


class RedisNestedWaitReservationGateway(NestedWaitReservationGateway):
    """Valkey-backed reservations survive an Orchestrator process restart."""

    def __init__(self, redis_url: str, *, key: str = "task_execution:nested_waits") -> None:
        self._redis_url = redis_url
        self._key = key

    def _client(self) -> redis.Redis:
        return redis.from_url(self._redis_url, decode_responses=False)

    @staticmethod
    def _serialize(reservation: NestedWaitReservation) -> bytes:
        return orjson.dumps(
            {
                "parent_task_id": reservation.parent_task_id,
                "child_task_id": reservation.child_task_id,
                "origin_worker_id": reservation.origin_worker_id,
                "created_at": reservation.created_at.isoformat(),
            }
        )

    @staticmethod
    def _deserialize(payload: bytes | str) -> NestedWaitReservation:
        data = orjson.loads(payload)
        created_at = data.get("created_at")
        return NestedWaitReservation(
            parent_task_id=str(data["parent_task_id"]),
            child_task_id=str(data["child_task_id"]),
            origin_worker_id=str(data["origin_worker_id"]),
            created_at=(
                datetime.fromisoformat(str(created_at))
                if created_at is not None
                else datetime.fromtimestamp(0, tz=UTC)
            ),
        )

    async def list(self) -> tuple[NestedWaitReservation, ...]:
        client = self._client()
        try:
            values = await client.hvals(self._key)
            return tuple(self._deserialize(value) for value in values)
        finally:
            await client.aclose()

    async def get(self, *, parent_task_id: str) -> NestedWaitReservation | None:
        client = self._client()
        try:
            value = await client.hget(self._key, parent_task_id)
            return None if value is None else self._deserialize(value)
        finally:
            await client.aclose()

    async def reserve(
        self,
        reservation: NestedWaitReservation,
        *,
        max_waiters: int,
    ) -> bool:
        if max_waiters <= 0:
            return False
        client = self._client()
        try:
            result = await client.eval(
                _RESERVE_SCRIPT,
                1,
                self._key,
                reservation.parent_task_id,
                self._serialize(reservation),
                max_waiters,
            )
            return bool(result)
        finally:
            await client.aclose()

    async def rebalance(self, *, max_waiters: int) -> tuple[NestedWaitReservation, ...]:
        client = self._client()
        try:
            payloads = await client.eval(
                _REBALANCE_SCRIPT,
                1,
                self._key,
                max(max_waiters, 0),
            )
            return tuple(self._deserialize(payload) for payload in payloads or ())
        finally:
            await client.aclose()

    async def release_by_parent(self, *, parent_task_id: str) -> None:
        client = self._client()
        try:
            await client.hdel(self._key, parent_task_id)
        finally:
            await client.aclose()

    async def release_by_child(self, *, child_task_id: str) -> None:
        await self._release_matching(child_task_id=child_task_id)

    async def release_by_worker(self, *, worker_id: str) -> None:
        await self._release_matching(worker_id=worker_id)

    async def _release_matching(
        self,
        *,
        child_task_id: str | None = None,
        worker_id: str | None = None,
    ) -> None:
        client = self._client()
        try:
            entries = await client.hgetall(self._key)
            stale_parents: list[bytes | str] = []
            for parent_id, payload in entries.items():
                reservation = self._deserialize(payload)
                if child_task_id is not None and reservation.child_task_id == child_task_id:
                    stale_parents.append(parent_id)
                elif worker_id is not None and reservation.origin_worker_id == worker_id:
                    stale_parents.append(parent_id)
            if stale_parents:
                await client.hdel(self._key, *stale_parents)
        finally:
            await client.aclose()
