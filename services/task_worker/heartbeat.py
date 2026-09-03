import asyncio
import time
from typing import Optional

import redis

from services.task_worker.deps.system_info_manager import get_sys_info
from services.task_worker.execution_slot import get_execution_slot_snapshot
from services.task_worker.helpers import get_worker_id

from src.logger import logger
from src.modules.task_execution.infra.transport.worker_heartbeat import HeartbeatPayload
from src.pipeline.execution_mode import PipelineExecutionMode

import config


class HeartbeatSender:
    def __init__(self) -> None:
        self._shutdown_event = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._redis = redis.Redis(
            host=config.VALKEY.VALKEY_HOST,
            port=config.VALKEY.VALKEY_PORT,
            password=config.VALKEY.VALKEY_PASSWORD,
            decode_responses=True,
        )

    async def _publish_with_retries(
            self,
            channel: str,
            payload: str,
            *,
            retries: int = 5,
            delay: float = 0.5,
            backoff: float = 2.0,
    ) -> None:
        last_exc: Optional[Exception] = None

        for attempt in range(1, retries + 1):
            try:
                await asyncio.to_thread(
                    self._redis.publish,
                    channel,
                    payload,
                )
                if attempt > 1:
                    logger.success(f"Successfully published after {attempt} attempts")
                return
            except Exception as exc:
                last_exc = exc
                logger.warning(f"VALKEY publish failed (attempt {attempt}/{retries}): {exc}")

                if attempt < retries:
                    await asyncio.sleep(delay)
                    delay *= backoff

        # если все попытки провалились
        raise last_exc

    async def start(self):
        if self._task:
            return
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self):
        self._shutdown_event.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run_loop(self):
        while not self._shutdown_event.is_set():
            try:
                try:
                    system_info = get_sys_info()

                except Exception:
                    logger.exception("Failed to get system info for heartbeat")
                    system_info = None

                execution_slot = get_execution_slot_snapshot()
                payload = HeartbeatPayload(
                    worker_id=get_worker_id(),
                    capabilities=[
                        PipelineExecutionMode.FULL,
                        PipelineExecutionMode.METADATA_ONLY,
                    ],
                    max_concurrent=int(config.TASK_WORKER.TASK_WORKER_MAX_CONCURRENT),
                    timestamp=int(time.time()),
                    active_task_id=execution_slot.active_task_id,
                    is_busy=execution_slot.is_busy,
                    available_slots=execution_slot.available_slots,
                    system_info=system_info,
                )
                payload_json = payload.model_dump_json()
                await self._publish_with_retries(
                    config.CELERY.CELERY_HEARTBEAT_CHANNEL,
                    payload_json,
                )
            except Exception:
                logger.exception("Failed to send heartbeat")

            await asyncio.sleep(config.TASK_WORKER.TASK_WORKER_HEARTBEAT_INTERVAL)
