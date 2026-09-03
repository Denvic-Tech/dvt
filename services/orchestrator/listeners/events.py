import asyncio
import contextlib

import orjson
from redis import asyncio as redis
from redis.exceptions import (
    ConnectionError as RedisConnectionError,
    ResponseError,
    TimeoutError as RedisTimeoutError,
)

from services.orchestrator.deps.worker_event_callbacks import handle_worker_event

from src.logger import logger
from src.schemas.worker_event_payload import WorkerEventPayload

import config

RECONNECT_DELAY_SEC = 1.0
_NOTIFICATION_DEDUP_TTL_SEC = 3600


class EventsStreamListener:
    def __init__(self) -> None:
        self._redis: redis.Redis | None = None
        self._task: asyncio.Task | None = None
        self._shutdown_event = asyncio.Event()
        self._group_ready = False

    def _create_redis(self) -> redis.Redis:
        return redis.Redis(
            host=config.VALKEY.VALKEY_HOST,
            port=config.VALKEY.VALKEY_PORT,
            password=config.VALKEY.VALKEY_PASSWORD,
            decode_responses=True,
        )

    async def start(self) -> None:
        if self._task:
            return
        self._shutdown_event.clear()
        self._task = asyncio.create_task(self._listen(), name="orchestrator-events-listener")

    async def stop(self) -> None:
        self._shutdown_event.set()
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        await self._disconnect()

    async def _ensure_group(self) -> None:
        assert self._redis is not None
        try:
            await self._redis.xgroup_create(
                name=config.ORCHESTRATOR.ORCH_EVENTS_STREAM,
                groupname=config.ORCHESTRATOR.ORCH_EVENTS_GROUP,
                id="0-0",
                mkstream=True,
            )
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def _ensure_ready(self) -> None:
        if self._redis is None:
            self._redis = self._create_redis()
            self._group_ready = False

        if not self._group_ready:
            await self._ensure_group()
            self._group_ready = True

    async def _disconnect(self) -> None:
        client = self._redis
        self._redis = None
        self._group_ready = False
        if client is not None:
            with contextlib.suppress(Exception):
                await client.close()

    async def _wait_before_retry(self) -> None:
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self._shutdown_event.wait(), timeout=RECONNECT_DELAY_SEC)

    async def _reserve_notification_delivery(self, message_id: str) -> bool:
        assert self._redis is not None
        key = (
            f"orchestrator:events:notification:{config.ORCHESTRATOR.ORCH_EVENTS_GROUP}:"
            f"{message_id}"
        )
        return bool(
            await self._redis.set(
                key,
                "1",
                nx=True,
                ex=_NOTIFICATION_DEDUP_TTL_SEC,
            )
        )

    async def _listen(self) -> None:
        while not self._shutdown_event.is_set():
            try:
                await self._ensure_ready()
                assert self._redis is not None

                claimed = await self._redis.xautoclaim(
                    name=config.ORCHESTRATOR.ORCH_EVENTS_STREAM,
                    groupname=config.ORCHESTRATOR.ORCH_EVENTS_GROUP,
                    consumername=config.ORCHESTRATOR.ORCH_EVENTS_CONSUMER,
                    min_idle_time=int(config.ORCHESTRATOR.ORCH_STREAM_PENDING_IDLE_SEC * 1000),
                    start_id="0-0",
                    count=config.ORCHESTRATOR.ORCH_EVENTS_BATCH_SIZE,
                )
                claimed_messages = claimed[1]
                entries = await self._redis.xreadgroup(
                    groupname=config.ORCHESTRATOR.ORCH_EVENTS_GROUP,
                    consumername=config.ORCHESTRATOR.ORCH_EVENTS_CONSUMER,
                    streams={config.ORCHESTRATOR.ORCH_EVENTS_STREAM: ">"},
                    count=config.ORCHESTRATOR.ORCH_EVENTS_BATCH_SIZE,
                    block=config.ORCHESTRATOR.ORCH_EVENTS_BLOCK_MS,
                )

                batches = [(config.ORCHESTRATOR.ORCH_EVENTS_STREAM, claimed_messages)]
                batches.extend(entries)
                for _stream, messages in batches:
                    for message_id, fields in messages:
                        try:
                            payload = fields.get("payload")
                            payload = WorkerEventPayload.model_validate(orjson.loads(payload))
                            forward_notifications = await self._reserve_notification_delivery(message_id)
                            await handle_worker_event(
                                payload,
                                forward_notifications=forward_notifications,
                            )
                        except asyncio.CancelledError:
                            raise
                        except Exception:
                            logger.exception("Failed to handle worker event", message_id=message_id)
                            continue

                        await self._redis.xack(
                            config.ORCHESTRATOR.ORCH_EVENTS_STREAM,
                            config.ORCHESTRATOR.ORCH_EVENTS_GROUP,
                            message_id,
                        )

            except asyncio.CancelledError:
                raise
            except ResponseError as exc:
                if "NOGROUP" in str(exc):
                    logger.warning(
                        "Orchestrator events consumer group is missing; recreating it",
                        stream=config.ORCHESTRATOR.ORCH_EVENTS_STREAM,
                        group=config.ORCHESTRATOR.ORCH_EVENTS_GROUP,
                    )
                    self._group_ready = False
                    await self._ensure_ready()
                    continue
                logger.exception("Failed to read orchestrator events stream")
                await self._disconnect()
                await self._wait_before_retry()
            except (RedisConnectionError, RedisTimeoutError, OSError):
                logger.warning(
                    "Lost valkey connection for orchestrator events stream; reconnecting",
                    stream=config.ORCHESTRATOR.ORCH_EVENTS_STREAM,
                    group=config.ORCHESTRATOR.ORCH_EVENTS_GROUP,
                )
                await self._disconnect()
                await self._wait_before_retry()
            except Exception:
                logger.exception("Failed to read orchestrator events stream")
                await self._disconnect()
                await self._wait_before_retry()
