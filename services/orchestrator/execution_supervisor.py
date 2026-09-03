import asyncio
import time
from collections import defaultdict
from contextlib import suppress

from sqlalchemy.ext.asyncio import AsyncSession

from services.orchestrator.celery_app import celery_app
from services.orchestrator.execution_registry import TaskExecutionRecord, TaskExecutionRegistry
from services.orchestrator.scheduler import TaskScheduler
from services.orchestrator.task_finalizer import (
    finalize_task_terminal_status,
    publish_task_terminal_event,
)

from src import enums
from src.clients.gateway_sdk.generated.models import OOMGuardConfig
from src.db.session import AsyncSessionLocal
from src.logger import logger
from src.modules.app_settings import get_app_settings
from src.modules.task_execution.domain.policies import terminal_status_for_termination_reason
from src.modules.task_execution.domain.types import TaskExecutionStatus, TaskTerminationReason
from src.modules.task_execution.facade import build_task_execution_facade
from src.pipeline.execution_mode import PipelineExecutionMode

import config


class TaskExecutionSupervisor:
    def __init__(
        self,
        *,
        registry: TaskExecutionRegistry,
        scheduler: TaskScheduler,
    ) -> None:
        self._registry = registry
        self._scheduler = scheduler
        self._task: asyncio.Task | None = None
        self._shutdown_event = asyncio.Event()
        self._host_last_kill_at: dict[str, float] = {}
        self._iteration_seq: int = 0
        self._started_at = time.time()

    async def start(self) -> None:
        if self._task is not None:
            return

        self._shutdown_event.clear()
        logger.info(
            "Starting execution supervisor",
            interval_sec=config.ORCHESTRATOR.ORCHESTRATOR_EXECUTION_SUPERVISOR_INTERVAL_SEC,
            stale_timeout_sec=config.ORCHESTRATOR.ORCHESTRATOR_EXECUTION_TELEMETRY_STALE_TIMEOUT_SEC,
            cooldown_sec=config.ORCHESTRATOR.ORCHESTRATOR_OOM_GUARD_COOLDOWN_SEC,
        )
        self._task = asyncio.create_task(self._run_loop(), name="orchestrator-execution-supervisor")

    async def stop(self) -> None:
        self._shutdown_event.set()
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task

            self._task = None
            logger.info("Execution supervisor stopped")

    async def _run_loop(self) -> None:
        consecutive_failed_iterations = 0
        while not self._shutdown_event.is_set():
            self._iteration_seq += 1
            success = await self._run_iteration(self._iteration_seq)
            if success:
                if consecutive_failed_iterations > 0:
                    logger.info(
                        "Execution supervisor recovered after failures",
                        recovered_iteration=self._iteration_seq,
                        previous_failures=consecutive_failed_iterations,
                    )
                consecutive_failed_iterations = 0
            else:
                consecutive_failed_iterations += 1
                logger.warning(
                    "Execution supervisor iteration completed with failures",
                    iteration=self._iteration_seq,
                    consecutive_failures=consecutive_failed_iterations,
                )

            try:
                await asyncio.wait_for(
                    self._shutdown_event.wait(),
                    timeout=config.ORCHESTRATOR.ORCHESTRATOR_EXECUTION_SUPERVISOR_INTERVAL_SEC,
                )
            except TimeoutError:
                continue

    async def _run_iteration(self, iteration: int) -> bool:
        async with AsyncSessionLocal() as session:
            step_results = [
                await self._run_step(
                    "reconcile_cancel_requested_tasks",
                    self._reconcile_cancel_requested_tasks(),
                    iteration=iteration,
                ),
                await self._run_step(
                    "reconcile_stale_executions",
                    self._reconcile_stale_executions(),
                    iteration=iteration,
                ),
                await self._run_step(
                    "reconcile_nested_wait_reservations",
                    self._reconcile_nested_wait_reservations(),
                    iteration=iteration,
                ),
                await self._run_step(
                    "apply_oom_guard",
                    self._apply_oom_guard(session=session),
                    iteration=iteration,
                ),
            ]

            return all(step_results)

    async def _reconcile_stale_executions(self) -> None:
        """Recover worker-owned executions from PostgreSQL, independent of telemetry memory."""
        now_ts = time.time()
        heartbeat_timeout = config.ORCHESTRATOR.ORCHESTRATOR_HEARTBEAT_TIMEOUT_SEC
        self._scheduler.registry.reap_dead_workers(now_ts)
        execution = build_task_execution_facade(celery_app=celery_app)
        active = await execution.list_worker_owned_active.execute(limit=1000)
        active_ids = {task.task_id for task in active}

        for task in active:
            worker_id = task.assigned_worker_id
            if worker_id is None:
                continue
            worker = self._scheduler.registry.get(worker_id)
            if worker is not None and worker.is_alive(now_ts, heartbeat_timeout):
                self._scheduler.registry.mark_busy(worker_id=worker_id, task_id=task.task_id)
                continue

            # After an Orchestrator restart the heartbeat registry is intentionally
            # empty. Give healthy workers one full heartbeat timeout to reappear;
            # after that absence itself is authoritative liveness evidence.
            if worker is None and (now_ts - self._started_at) < heartbeat_timeout:
                continue

            finalized = await execution.finalize_reconciled.execute(
                task_id=task.task_id,
                termination_reason=TaskTerminationReason.WORKER_LOST.value,
                message="Task worker heartbeat was lost",
            )
            if finalized is None:
                continue

            await self._cleanup_execution_runtime(
                task_id=task.task_id,
                worker_id=worker_id,
                execution=execution,
            )
            await publish_task_terminal_event(
                task_id=task.task_id,
                user_id=task.user_id,
                project_id=task.project_id,
                mode=PipelineExecutionMode(task.mode),
                status=TaskExecutionStatus.ERROR,
                error_message="Task worker heartbeat was lost",
            )
            logger.warning(
                "Finalized PostgreSQL active task after worker heartbeat loss",
                task_id=task.task_id,
                worker_id=worker_id,
            )

        # Telemetry remains a cache only. Garbage-collect orphaned stale records,
        # but never require one to discover WORKER_LOST.
        stale_records = await self._registry.get_stale(
            now_ts=now_ts,
            stale_timeout_sec=config.ORCHESTRATOR.ORCHESTRATOR_EXECUTION_TELEMETRY_STALE_TIMEOUT_SEC,
        )
        for record in stale_records:
            if record.task_id not in active_ids:
                await self._cleanup_execution_runtime(
                    task_id=record.task_id,
                    worker_id=record.worker_id,
                    execution=execution,
                )

    async def _cleanup_execution_runtime(
        self,
        *,
        task_id: str,
        worker_id: str,
        execution,
    ) -> None:
        await self._registry.remove(task_id)
        self._scheduler.registry.mark_idle(worker_id=worker_id, task_id=task_id)
        try:
            await execution.release_nested_wait.execute(
                parent_task_id=task_id,
                child_task_id=task_id,
                worker_id=worker_id,
            )
        except Exception as exc:
            logger.warning(
                "Failed to cleanup nested wait during execution reconciliation",
                task_id=task_id,
                worker_id=worker_id,
                error=str(exc),
            )

    async def _reconcile_nested_wait_reservations(self) -> None:
        execution = build_task_execution_facade(celery_app=celery_app)
        reservations = await execution.nested_wait_gateway.list()
        terminal_statuses = {
            TaskExecutionStatus.SUCCESS,
            TaskExecutionStatus.ERROR,
            TaskExecutionStatus.CANCELLED,
        }
        now_ts = time.time()
        for reservation in reservations:
            worker = self._scheduler.registry.get(reservation.origin_worker_id)
            worker_alive = worker is not None and worker.is_alive(
                now_ts,
                config.ORCHESTRATOR.ORCHESTRATOR_HEARTBEAT_TIMEOUT_SEC,
            )
            parent = await execution.get_task.execute(task_id=reservation.parent_task_id)
            child = await execution.get_task.execute(task_id=reservation.child_task_id)

            if (
                not worker_alive
                or parent is None
                or child is None
                or TaskExecutionStatus(parent.status) in terminal_statuses
                or TaskExecutionStatus(child.status) in terminal_statuses
            ):
                await execution.release_nested_wait.execute(
                    parent_task_id=reservation.parent_task_id
                )

        alive_worker_ids = {
            worker.worker_id
            for worker in self._scheduler.registry.get_alive_workers(now_ts)
            if str(getattr(worker.status, "value", worker.status)).lower()
            == enums.WorkerStatus.ONLINE.value
        }
        evicted = await execution.nested_wait_gateway.rebalance(
            max_waiters=max(len(alive_worker_ids) - 1, 0)
        )
        for reservation in evicted:
            requested = await self._scheduler.request_task_hard_stop(
                task_id=reservation.parent_task_id,
                reason=TaskTerminationReason.NESTED_WAIT_CAPACITY_LOST.value,
            )
            if requested:
                logger.warning(
                    "Nested wait failed after alive capacity reduction",
                    parent_task_id=reservation.parent_task_id,
                    child_task_id=reservation.child_task_id,
                    origin_worker_id=reservation.origin_worker_id,
                    alive_workers=len(alive_worker_ids),
                )

    async def _run_step(self, step_name: str, step_coro, *, iteration: int) -> bool:
        try:
            await step_coro
            return True
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception(
                "Execution supervisor step failed",
                step=step_name,
                iteration=iteration,
                error=str(exc),
            )
            return False

    async def _reconcile_cancel_requested_tasks(self) -> None:
        execution_flow = build_task_execution_facade(celery_app=celery_app)
        tasks = list(
            await execution_flow.list_for_reconciliation.execute(
                statuses=[TaskExecutionStatus.CANCEL_REQUESTED.value],
                limit=1000,
            )
        )

        if not tasks:
            return

        now_ts = time.time()
        for task in tasks:
            try:
                execution = await self._registry.get(task.task_id)
                execution_is_stale = (
                    execution is not None
                    and execution.is_stale(
                        now_ts,
                        config.ORCHESTRATOR.ORCHESTRATOR_EXECUTION_TELEMETRY_STALE_TIMEOUT_SEC,
                    )
                )
                reference_ts = task.updated_at.timestamp() if task.updated_at is not None else now_ts
                cancellation_age_sec = now_ts - reference_ts
                if (
                    task.termination_reason == TaskTerminationReason.USER_STOP.value
                    and execution is not None
                    and cancellation_age_sec >= config.ORCHESTRATOR.TASK_STOP_GRACE_PERIOD_SEC
                ):
                    # Keep USER_STOP as the reason: this is escalation of the
                    # same request, not a new HARD_STOP command. A stale runtime
                    # record must not block cancellation reconciliation forever.
                    self._scheduler.terminate_execution(task_id=task.task_id)
                    if not execution_is_stale:
                        continue

                if execution is not None and not execution_is_stale:
                    continue
                terminal_delay_sec = (
                    config.ORCHESTRATOR.TASK_STOP_GRACE_PERIOD_SEC
                    if task.termination_reason == TaskTerminationReason.USER_STOP.value
                    else config.ORCHESTRATOR.ORCHESTRATOR_EXECUTION_TELEMETRY_STALE_TIMEOUT_SEC
                )
                if cancellation_age_sec < terminal_delay_sec:
                    continue
                if (
                    task.termination_reason == TaskTerminationReason.USER_STOP.value
                    and execution is None
                ):
                    self._scheduler.terminate_execution(task_id=task.task_id)

                terminal_status = TaskExecutionStatus(
                    terminal_status_for_termination_reason(task.termination_reason)
                )
                error_message = None
                if terminal_status == TaskExecutionStatus.ERROR:
                    error_message = (
                        "Task terminated by OOM guard"
                        if task.termination_reason == TaskTerminationReason.OOM_GUARD.value
                        else f"Task terminated: {task.termination_reason or 'unknown reason'}"
                    )
                finalized = await finalize_task_terminal_status(
                    task_id=task.task_id,
                    user_id=task.user_id,
                    project_id=task.project_id,
                    worker_id=task.assigned_worker_id,
                    mode=PipelineExecutionMode(task.mode),
                    status=terminal_status,
                    termination_reason=task.termination_reason,
                    error_message=error_message,
                )
                if finalized:
                    logger.info(
                        "Finalized task after termination request",
                        task_id=task.task_id,
                        worker_id=task.assigned_worker_id,
                        status=terminal_status.value,
                        termination_reason=task.termination_reason,
                    )
            except Exception as exc:
                logger.warning(
                    "Skipping CANCEL_REQUESTED reconciliation after concurrent lifecycle change",
                    task_id=task.task_id,
                    error=str(exc),
                )

    async def _apply_oom_guard(self, session: AsyncSession) -> None:
        app_settings = await get_app_settings(session=session)
        oom_guard_config = app_settings.runtime.oom_guard

        if oom_guard_config.mode == enums.OOMGuardMode.DISABLED:
            return

        records = await self._registry.all()
        if not records:
            return

        if oom_guard_config.mode == enums.OOMGuardMode.HOST_PRESSURE:
            await self._apply_host_pressure_guard(records, oom_guard_config)
            return

        if oom_guard_config.mode == enums.OOMGuardMode.WORKER_THRESHOLD:
            await self._apply_worker_threshold_guard(records, oom_guard_config)
            return

    async def _apply_host_pressure_guard(
        self,
        records: list[TaskExecutionRecord],
        settings: OOMGuardConfig,
    ) -> None:
        if settings.host_threshold_percent is None:
            return

        by_host: dict[str, list[TaskExecutionRecord]] = defaultdict(list)
        for record in records:
            by_host[record.hostname].append(record)

        now_ts = time.time()
        for hostname, host_records in by_host.items():
            host_pressure = max(record.system_ram_used_percent for record in host_records)
            if host_pressure < settings.host_threshold_percent:
                continue

            last_kill_at = self._host_last_kill_at.get(hostname, 0.0)
            if (now_ts - last_kill_at) < config.ORCHESTRATOR.ORCHESTRATOR_OOM_GUARD_COOLDOWN_SEC:
                continue

            victim = max(host_records, key=lambda _record: _record.rss_bytes)
            requested = await self._request_task_kill(
                task_id=victim.task_id,
                reason=TaskTerminationReason.OOM_GUARD.value,
            )
            if requested:
                self._host_last_kill_at[hostname] = now_ts
                logger.warning(
                    "OOM guard requested hard stop for task",
                    task_id=victim.task_id,
                    worker_id=victim.worker_id,
                    hostname=hostname,
                    pid=victim.pid,
                    rss_bytes=victim.rss_bytes,
                    system_ram_used_percent=victim.system_ram_used_percent,
                )

    async def _apply_worker_threshold_guard(
        self,
        records: list[TaskExecutionRecord],
        settings: OOMGuardConfig,
    ) -> None:
        if settings.worker_threshold_type is None:
            return

        now_ts = time.time()
        candidates: list[tuple[float, TaskExecutionRecord]] = []
        for record in records:
            last_kill_at = self._host_last_kill_at.get(record.hostname, 0.0)
            if (now_ts - last_kill_at) < config.ORCHESTRATOR.ORCHESTRATOR_OOM_GUARD_COOLDOWN_SEC:
                continue

            if settings.worker_threshold_type == enums.OOMWorkerThresholdType.PERCENT:
                worker_memory_used_percent = self._get_worker_memory_used_percent(record)
                if (
                    worker_memory_used_percent is None
                    or settings.worker_threshold_percent is None
                    or worker_memory_used_percent < settings.worker_threshold_percent
                ):
                    continue
                candidates.append((worker_memory_used_percent, record))
                continue

            if settings.worker_threshold_type == enums.OOMWorkerThresholdType.ABSOLUTE_MB:
                if settings.worker_threshold_mb is None:
                    continue
                threshold_bytes = settings.worker_threshold_mb * 1024 * 1024
                if record.rss_bytes < threshold_bytes:
                    continue
                candidates.append((float(record.rss_bytes), record))

        if not candidates:
            return

        _, victim = max(candidates, key=lambda item: item[0])
        requested = await self._request_task_kill(
            task_id=victim.task_id,
            reason=TaskTerminationReason.OOM_GUARD.value,
        )
        if requested:
            self._host_last_kill_at[victim.hostname] = now_ts
            logger.warning(
                "Worker-threshold OOM guard requested hard stop for task",
                task_id=victim.task_id,
                worker_id=victim.worker_id,
                hostname=victim.hostname,
                pid=victim.pid,
                rss_bytes=victim.rss_bytes,
                memory_limit_bytes=victim.memory_limit_bytes,
                worker_memory_used_percent=self._get_worker_memory_used_percent(victim),
            )

    async def _request_task_kill(self, *, task_id: str, reason: str) -> bool:
        execution = build_task_execution_facade(celery_app=celery_app)
        task = await execution.kill_task.execute(task_id=task_id, reason=reason)
        return task is not None and task.status == "CANCEL_REQUESTED"

    @staticmethod
    def _get_worker_memory_used_percent(record: TaskExecutionRecord) -> float | None:
        if record.memory_limit_bytes is None or record.memory_limit_bytes <= 0:
            return None
        return (float(record.rss_bytes) / float(record.memory_limit_bytes)) * 100.0
