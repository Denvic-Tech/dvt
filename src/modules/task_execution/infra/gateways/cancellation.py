"""Cooperative task cancellation transport.

PostgreSQL remains authoritative. Valkey pub/sub only wakes the worker quickly; a
periodic DB check closes notification/reconnect races.
"""

import asyncio
from collections.abc import Callable

import sqlalchemy as sa
from redis import asyncio as redis
from redis.exceptions import (
    ConnectionError as RedisConnectionError,
    TimeoutError as RedisTimeoutError,
)
from sqlalchemy.ext.asyncio import AsyncSession

from src.logger import logger

from ...domain.gateways import TaskCancellationGateway
from ...domain.types import TaskExecutionStatus
from ..db_models import TaskRecord


class ValkeyTaskCancellationGateway(TaskCancellationGateway):
    def __init__(
        self,
        session_factory: Callable[[], AsyncSession],
        *,
        redis_url: str,
        poll_interval_sec: float,
        channel_prefix: str = "task_execution:cancel",
    ) -> None:
        self._session_factory = session_factory
        self._redis_url = redis_url
        self._poll_interval_sec = max(float(poll_interval_sec), 0.05)
        self._channel_prefix = channel_prefix

    def _channel(self, task_id: str) -> str:
        return f"{self._channel_prefix}:{task_id}"

    async def _read_authoritative_reason(self, *, task_id: str) -> str | None:
        async with self._session_factory() as session:
            result = await session.execute(
                sa.select(TaskRecord.status, TaskRecord.termination_reason).where(
                    TaskRecord.task_id == task_id
                )
            )
            task = result.one_or_none()
        if task is None:
            return "UNKNOWN"
        status, reason = task
        if status in (TaskExecutionStatus.CANCEL_REQUESTED, TaskExecutionStatus.CANCELLED):
            return str(reason or "USER_STOP")
        return None

    async def notify_stop(self, *, task_id: str) -> None:
        """Best-effort wakeup only; PostgreSQL STOP state is already authoritative."""
        client = redis.from_url(self._redis_url, decode_responses=True)
        try:
            try:
                await asyncio.wait_for(
                    client.publish(self._channel(task_id), task_id),
                    timeout=self._poll_interval_sec,
                )
            except (RedisConnectionError, RedisTimeoutError, OSError, asyncio.TimeoutError) as exc:
                logger.warning(
                    "Task STOP was committed but Valkey notification failed",
                    task_id=task_id,
                    error=str(exc),
                )
        finally:
            try:
                await client.aclose()
            except (RedisConnectionError, RedisTimeoutError, OSError):
                pass

    async def get_stop_reason(self, *, task_id: str) -> str | None:
        return await self._read_authoritative_reason(task_id=task_id)

    async def wait_for_stop(self, *, task_id: str) -> str:
        """Observe authoritative DB state while treating pub/sub as an optional wakeup."""
        while True:
            reason = await self._read_authoritative_reason(task_id=task_id)
            if reason is not None:
                return reason

            client = redis.from_url(self._redis_url, decode_responses=True)
            pubsub = client.pubsub()
            try:
                try:
                    # A bounded subscribe attempt is important: an unavailable
                    # Valkey must never suspend PostgreSQL polling indefinitely.
                    await asyncio.wait_for(
                        pubsub.subscribe(self._channel(task_id)),
                        timeout=self._poll_interval_sec,
                    )
                except (
                    RedisConnectionError,
                    RedisTimeoutError,
                    OSError,
                    asyncio.TimeoutError,
                ):
                    await asyncio.sleep(self._poll_interval_sec)
                    continue

                while True:
                    reason = await self._read_authoritative_reason(task_id=task_id)
                    if reason is not None:
                        return reason

                    try:
                        message = await pubsub.get_message(
                            ignore_subscribe_messages=True,
                            timeout=self._poll_interval_sec,
                        )
                    except (RedisConnectionError, RedisTimeoutError, OSError):
                        break

                    if message is not None:
                        reason = await self._read_authoritative_reason(task_id=task_id)
                        if reason is not None:
                            return reason
            finally:
                try:
                    await pubsub.aclose()
                except (RedisConnectionError, RedisTimeoutError, OSError):
                    pass
                try:
                    await client.aclose()
                except (RedisConnectionError, RedisTimeoutError, OSError):
                    pass

            await asyncio.sleep(self._poll_interval_sec)


# Compatibility name for callers/tests from the first refactor iteration.
DatabaseTaskCancellationGateway = ValkeyTaskCancellationGateway
