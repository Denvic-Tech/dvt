import asyncio
import contextlib
import time

from redis import asyncio as redis
from redis.exceptions import (
    ConnectionError as RedisConnectionError,
    TimeoutError as RedisTimeoutError,
)

from services.orchestrator.deps.worker_registry import get_worker_registry

from src.logger import logger
from src.modules.task_execution.infra.transport.worker_heartbeat import HeartbeatPayload

import config

RECONNECT_DELAY_SEC = 1.0


class HeartbeatListener:
    def __init__(self) -> None:
        self._redis: redis.Redis | None = None
        self._pubsub = None
        self._task: asyncio.Task | None = None
        self._shutdown_event = asyncio.Event()
        self._window_started_at: float | None = None
        self._messages_in_window = 0
        self._workers_in_window: set[str] = set()

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
        self._task = asyncio.create_task(self._listen(), name="orchestrator-heartbeat-listener")

    async def stop(self) -> None:
        self._shutdown_event.set()
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        await self._disconnect()

    async def _connect(self) -> None:
        if self._redis is not None and self._pubsub is not None:
            return

        await self._disconnect()
        self._redis = self._create_redis()
        self._pubsub = self._redis.pubsub()
        await self._pubsub.subscribe(config.CELERY.CELERY_HEARTBEAT_CHANNEL)
        logger.info(
            "Worker heartbeat listener subscribed",
            channel=config.CELERY.CELERY_HEARTBEAT_CHANNEL,
            valkey_host=config.VALKEY.VALKEY_HOST,
            valkey_port=config.VALKEY.VALKEY_PORT,
        )

    async def _disconnect(self) -> None:
        pubsub = self._pubsub
        client = self._redis
        self._pubsub = None
        self._redis = None

        if pubsub is not None:
            with contextlib.suppress(Exception):
                await pubsub.close()

        if client is not None:
            with contextlib.suppress(Exception):
                await client.close()

    async def _wait_before_retry(self) -> None:
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self._shutdown_event.wait(), timeout=RECONNECT_DELAY_SEC)

    def _record_heartbeat_window(self, *, worker_id: str, received_at: float) -> None:
        if self._window_started_at is None:
            self._window_started_at = received_at

        self._messages_in_window += 1
        self._workers_in_window.add(worker_id)

        if received_at - self._window_started_at < 30.0:
            return

        logger.info(
            "Worker heartbeat listener summary",
            channel=config.CELERY.CELERY_HEARTBEAT_CHANNEL,
            interval_sec=received_at - self._window_started_at,
            messages=self._messages_in_window,
            unique_workers=len(self._workers_in_window),
            workers=sorted(self._workers_in_window),
        )
        self._window_started_at = received_at
        self._messages_in_window = 0
        self._workers_in_window.clear()

    async def _listen(self) -> None:
        registry = get_worker_registry()

        while not self._shutdown_event.is_set():
            try:
                await self._connect()
                assert self._pubsub is not None

                async for message in self._pubsub.listen():
                    if self._shutdown_event.is_set():
                        return
                    if message.get("type") != "message":
                        continue
                    data = message.get("data")
                    try:
                        received_at = time.time()
                        if isinstance(data, str):
                            hb = HeartbeatPayload.model_validate_json(data)
                        elif isinstance(data, bytes):
                            hb = HeartbeatPayload.model_validate_json(data.decode("utf-8"))
                        else:
                            hb = HeartbeatPayload.model_validate(data)

                        heartbeat_transport_delay_sec = max(received_at - float(hb.timestamp), 0.0)
                        if heartbeat_transport_delay_sec >= (
                                config.TASK_WORKER.TASK_WORKER_HEARTBEAT_INTERVAL * 2
                        ):
                            logger.warning(
                                "Received delayed worker heartbeat payload",
                                worker_id=hb.worker_id,
                                channel=config.CELERY.CELERY_HEARTBEAT_CHANNEL,
                                heartbeat_transport_delay_sec=heartbeat_transport_delay_sec,
                                worker_timestamp=float(hb.timestamp),
                                received_at=received_at,
                            )

                        await registry.update_from_heartbeat(
                            worker_id=hb.worker_id,
                            max_concurrent=hb.max_concurrent,
                            timestamp=hb.timestamp,
                            received_at=received_at,
                            active_task_id=hb.active_task_id,
                            is_busy=hb.is_busy,
                            available_slots=hb.available_slots,
                            system_info=hb.system_info,
                            capabilities=set(hb.capabilities),
                        )
                        self._record_heartbeat_window(worker_id=hb.worker_id, received_at=received_at)
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        logger.exception("Failed to process heartbeat message")

                if self._shutdown_event.is_set():
                    return

                logger.warning(
                    "Worker heartbeat subscription ended unexpectedly; reconnecting",
                    channel=config.CELERY.CELERY_HEARTBEAT_CHANNEL,
                )
            except asyncio.CancelledError:
                raise
            except (RedisConnectionError, RedisTimeoutError, OSError):
                logger.warning(
                    "Lost valkey connection for worker heartbeat listener; reconnecting",
                    channel=config.CELERY.CELERY_HEARTBEAT_CHANNEL,
                )
            except Exception:
                logger.exception("Worker heartbeat listener failed")

            await self._disconnect()
            await self._wait_before_retry()
