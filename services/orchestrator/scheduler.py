import asyncio

from services.orchestrator.celery_app import celery_app
from services.orchestrator.task_finalizer import publish_task_terminal_event

from src.exception_registry import TaskNotFoundException
from src.logger import logger
from src.modules.task_execution.domain.types import TaskExecutionStatus, TaskTerminationReason
from src.modules.task_execution.facade import build_task_execution_facade
from src.pipeline.execution_mode import PipelineExecutionMode

import config


class TaskScheduler:
    """Orchestrator composition loop for durable dispatch and cancellation.

    It deliberately has no pending-task memory and never chooses a worker.  The
    outbox is the durable source of dispatch work; Celery chooses the consumer.
    """

    def __init__(self, *, registry, interval_sec: int | float | None = None) -> None:
        self.registry = registry
        self.interval_sec = interval_sec or config.ORCHESTRATOR.ORCHESTRATOR_SCHEDULER_INTERVAL_SEC
        self._execution = build_task_execution_facade(celery_app=celery_app)
        self._loop_task: asyncio.Task | None = None
        self._shutdown_event = asyncio.Event()
        self._tick_lock = asyncio.Lock()
        self._log = logger.bind(component="TaskDispatchPublisher")

    async def handle_task_cancel(self, task_id: str) -> bool:
        return await self.request_task_stop(
            task_id=task_id,
            reason=TaskTerminationReason.USER_STOP,
        )

    async def request_task_stop(self, *, task_id: str, reason: str) -> bool:
        """Persist cooperative cancellation and wake the execution child through Valkey."""
        task = await self._execution.request_stop.execute(task_id=task_id, reason=reason)
        if task is None:
            raise TaskNotFoundException(status_code=404, detail=f"Task ID={task_id} not found.")
        if task.status == "CANCELLED" and task.termination_reason == reason:
            await self._execution.release_nested_wait.execute(child_task_id=task_id)
            await publish_task_terminal_event(
                task_id=task.task_id,
                user_id=task.user_id,
                project_id=task.project_id,
                mode=PipelineExecutionMode(task.mode),
                status=TaskExecutionStatus.CANCELLED,
            )
        return task.status not in {"SUCCESS", "ERROR", "CANCELLED"} or reason == task.termination_reason

    async def request_task_hard_stop(self, *, task_id: str, reason: str) -> bool:
        task = await self._execution.kill_task.execute(task_id=task_id, reason=reason)
        if task is None:
            raise TaskNotFoundException(status_code=404, detail=f"Task ID={task_id} not found.")
        if task.status == "CANCELLED" and task.termination_reason == reason:
            await self._execution.release_nested_wait.execute(child_task_id=task_id)
            await publish_task_terminal_event(
                task_id=task.task_id,
                user_id=task.user_id,
                project_id=task.project_id,
                mode=PipelineExecutionMode(task.mode),
                status=TaskExecutionStatus.CANCELLED,
            )
        return task.status not in {"SUCCESS", "ERROR", "CANCELLED"} or reason == task.termination_reason

    def terminate_execution(self, *, task_id: str) -> None:
        """Hard-terminate an already marked execution without changing its reason."""
        self._execution.terminate_execution.execute(task_id=task_id)

    async def start(self) -> None:
        if self._loop_task is None:
            self._shutdown_event.clear()
            self._loop_task = asyncio.create_task(self._run_loop(), name="task-dispatch-publisher")

    async def stop(self) -> None:
        self._shutdown_event.set()
        if self._loop_task is not None:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
            self._loop_task = None

    async def _run_loop(self) -> None:
        while not self._shutdown_event.is_set():
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                self._log.exception("Task dispatch outbox publisher failed")
            try:
                await asyncio.wait_for(self._shutdown_event.wait(), timeout=self.interval_sec)
            except TimeoutError:
                pass

    async def _tick(self) -> None:
        # One Orchestrator process owns one publisher loop. The lock also guards
        # accidental concurrent/manual ticks inside the same process.
        async with self._tick_lock:
            dead_workers = self.registry.reap_dead_workers(__import__("time").time())
            if dead_workers:
                self._log.warning(
                    "Detected offline workers",
                    worker_ids=[item.worker_id for item in dead_workers],
                )
            published = await self._execution.publish_pending_dispatches.execute()
            if published:
                self._log.info("Published durable task dispatches", count=published)
