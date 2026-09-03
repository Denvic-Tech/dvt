import asyncio
import contextlib
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import aiohttp

from services.gateway.update_runtime.client import (
    InstallationManagerClient,
    InstallationManagerHTTPError,
    InstallationManagerNoJob,
    InstallationManagerUnavailable,
    UpdateJobSummary,
)

from src.clients.scheduler_client import SchedulerClient
from src.enums import WorkerStatus
from src.logger import logger
from src.runtime.async_runtime import shared_orchestrator
from src.schemas.http.system import SystemStateValue

import config


@dataclass(frozen=True)
class SystemStateSnapshot:
    state: SystemStateValue
    retry_after_sec: int
    checked_at: datetime


class ServiceReadinessChecker:
    def __init__(self) -> None:
        self._scheduler_session: aiohttp.ClientSession | None = None
        self._scheduler_client: SchedulerClient | None = None

    async def start(self) -> None:
        if self._scheduler_session is not None:
            return
        self._scheduler_session = aiohttp.ClientSession(
            base_url=config.PROJECT_SCHEDULER.PROJECT_SCHEDULER_URL
        )
        self._scheduler_client = SchedulerClient(
            scheduler_url=config.PROJECT_SCHEDULER.PROJECT_SCHEDULER_URL,
            session=self._scheduler_session,
        )

    async def is_ready(self) -> bool:
        if self._scheduler_client is None:
            return False
        try:
            orchestrator = await shared_orchestrator.get()
            workers = await orchestrator.get_system_stats()
            await self._scheduler_client.system_status()
        except Exception as exc:
            logger.debug("System readiness probe failed: {}", exc)
            return False
        return any(worker.status == WorkerStatus.ONLINE for worker in workers)

    async def close(self) -> None:
        if self._scheduler_session is not None:
            await self._scheduler_session.close()
        self._scheduler_session = None
        self._scheduler_client = None


class SystemStateMonitor:
    def __init__(
        self,
        manager_client: InstallationManagerClient,
        readiness_checker: ServiceReadinessChecker,
        *,
        poll_interval_sec: float,
        retry_after_sec: int,
        manager_stale_timeout_sec: float,
        readiness_timeout_sec: float,
        recent_update_window_sec: float,
        readiness_probe_timeout_sec: float,
        now: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        self._manager_client = manager_client
        self._readiness_checker = readiness_checker
        self._poll_interval_sec = poll_interval_sec
        self._retry_after_sec = retry_after_sec
        self._manager_stale_timeout_sec = manager_stale_timeout_sec
        self._readiness_timeout_sec = readiness_timeout_sec
        self._recent_update_window_sec = recent_update_window_sec
        self._readiness_probe_timeout_sec = readiness_probe_timeout_sec
        self._now = now or (lambda: datetime.now(UTC))
        self._monotonic = monotonic or time.monotonic

        self._snapshot = SystemStateSnapshot(
            state=SystemStateValue.DEGRADED,
            retry_after_sec=retry_after_sec,
            checked_at=self._now(),
        )
        self._active_job_id: str | None = None
        self._resolved_job_id: str | None = None
        self._last_manager_contact_at: float | None = None
        self._readiness_started_at: float | None = None
        self._refresh_lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None

    @property
    def snapshot(self) -> SystemStateSnapshot:
        return self._snapshot

    async def start(self) -> None:
        if self._task is not None:
            return
        await self._readiness_checker.start()
        await self._safe_refresh()
        self._task = asyncio.create_task(self._run(), name="system-state-monitor")

    async def close(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        await self._readiness_checker.close()
        await self._manager_client.close()

    async def mark_updating(self, job_id: str | None) -> None:
        async with self._refresh_lock:
            self._active_job_id = job_id
            self._resolved_job_id = None
            self._last_manager_contact_at = self._monotonic()
            self._readiness_started_at = None
            self._set_state(SystemStateValue.UPDATING)

    async def refresh(self) -> None:
        async with self._refresh_lock:
            try:
                summary = await self._manager_client.get_current_job_summary()
            except InstallationManagerNoJob:
                await self._handle_missing_job()
            except (InstallationManagerUnavailable, InstallationManagerHTTPError) as exc:
                await self._handle_manager_unavailable(exc)
            except Exception as exc:
                await self._handle_manager_unavailable(exc)
            else:
                self._last_manager_contact_at = self._monotonic()
                await self._handle_summary(summary)

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self._poll_interval_sec)
            await self._safe_refresh()

    async def _safe_refresh(self) -> None:
        try:
            await self.refresh()
        except Exception:
            logger.exception("Unexpected system state refresh failure")
            self._set_state(SystemStateValue.DEGRADED)

    async def _handle_summary(self, summary: UpdateJobSummary) -> None:
        if summary.state == "running":
            self._active_job_id = summary.id
            self._resolved_job_id = None
            self._readiness_started_at = None
            self._set_state(SystemStateValue.UPDATING)
            return

        if summary.state == "failed":
            self._active_job_id = None
            self._resolved_job_id = summary.id
            self._readiness_started_at = None
            self._set_state(SystemStateValue.DEGRADED)
            return

        if summary.state != "succeeded":
            self._set_state(SystemStateValue.DEGRADED)
            return

        should_wait_for_readiness = self._resolved_job_id != summary.id and (
            self._active_job_id == summary.id or self._is_recent(summary.finished_at)
        )
        if should_wait_for_readiness:
            await self._finish_update_when_ready(summary.id)
            return

        self._active_job_id = None
        self._readiness_started_at = None
        self._set_state(
            SystemStateValue.READY if await self._services_ready() else SystemStateValue.DEGRADED
        )

    async def _finish_update_when_ready(self, job_id: str) -> None:
        now_monotonic = self._monotonic()
        if self._readiness_started_at is None:
            self._readiness_started_at = now_monotonic
        self._active_job_id = job_id

        if await self._services_ready():
            self._active_job_id = None
            self._resolved_job_id = job_id
            self._readiness_started_at = None
            self._set_state(SystemStateValue.READY)
            return

        if now_monotonic - self._readiness_started_at >= self._readiness_timeout_sec:
            self._active_job_id = None
            self._resolved_job_id = job_id
            self._readiness_started_at = None
            self._set_state(SystemStateValue.DEGRADED)
            return

        self._set_state(SystemStateValue.UPDATING)

    async def _handle_missing_job(self) -> None:
        if self._snapshot.state == SystemStateValue.UPDATING and self._active_job_id:
            if not self._manager_state_is_stale():
                self._set_state(SystemStateValue.UPDATING)
                return
            self._active_job_id = None
            self._readiness_started_at = None
            self._set_state(SystemStateValue.DEGRADED)
            return

        self._set_state(
            SystemStateValue.READY if await self._services_ready() else SystemStateValue.DEGRADED
        )

    async def _handle_manager_unavailable(self, exc: Exception) -> None:
        logger.debug("Installation manager state probe failed: {}", exc)
        if self._snapshot.state == SystemStateValue.UPDATING and self._active_job_id:
            if not self._manager_state_is_stale():
                self._set_state(SystemStateValue.UPDATING)
                return
            self._active_job_id = None
            self._readiness_started_at = None
        self._set_state(SystemStateValue.DEGRADED)

    async def _services_ready(self) -> bool:
        try:
            return await asyncio.wait_for(
                self._readiness_checker.is_ready(),
                timeout=self._readiness_probe_timeout_sec,
            )
        except TimeoutError:
            return False

    def _manager_state_is_stale(self) -> bool:
        if self._last_manager_contact_at is None:
            return True
        return self._monotonic() - self._last_manager_contact_at >= self._manager_stale_timeout_sec

    def _is_recent(self, finished_at: datetime | None) -> bool:
        if finished_at is None:
            return False
        if finished_at.tzinfo is None:
            finished_at = finished_at.replace(tzinfo=UTC)
        return (self._now() - finished_at).total_seconds() <= self._recent_update_window_sec

    def _set_state(self, state: SystemStateValue) -> None:
        self._snapshot = SystemStateSnapshot(
            state=state,
            retry_after_sec=self._retry_after_sec,
            checked_at=self._now(),
        )
