from datetime import UTC, datetime, timedelta

import pytest

from services.gateway.update_runtime.client import (
    InstallationManagerNoJob,
    InstallationManagerUnavailable,
    UpdateJobSummary,
)
from services.gateway.update_runtime.monitor import SystemStateMonitor

from src.schemas.http.system import SystemStateValue


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 7, 22, tzinfo=UTC)
        self.monotonic = 0.0

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)
        self.monotonic += seconds


class FakeManagerClient:
    def __init__(self, result):
        self.result = result

    async def get_current_job_summary(self) -> UpdateJobSummary:
        if isinstance(self.result, Exception):
            raise self.result
        return self.result

    async def close(self) -> None:
        return None


class FakeReadinessChecker:
    def __init__(self, ready: bool):
        self.ready = ready

    async def start(self) -> None:
        return None

    async def is_ready(self) -> bool:
        return self.ready

    async def close(self) -> None:
        return None


def _summary(clock: Clock, state: str, *, finished: bool = False) -> UpdateJobSummary:
    return UpdateJobSummary(
        id="job-1",
        kind="update",
        state=state,
        version="1.2.3",
        started_at=clock.now - timedelta(minutes=1),
        finished_at=clock.now if finished else None,
    )


def _monitor(clock: Clock, manager_result, *, ready: bool) -> SystemStateMonitor:
    return SystemStateMonitor(
        manager_client=FakeManagerClient(manager_result),  # type: ignore[arg-type]
        readiness_checker=FakeReadinessChecker(ready),  # type: ignore[arg-type]
        poll_interval_sec=2,
        retry_after_sec=3,
        manager_stale_timeout_sec=60,
        readiness_timeout_sec=300,
        recent_update_window_sec=600,
        readiness_probe_timeout_sec=1,
        now=lambda: clock.now,
        monotonic=lambda: clock.monotonic,
    )


@pytest.mark.asyncio
async def test_no_job_and_healthy_services_is_ready() -> None:
    clock = Clock()
    monitor = _monitor(clock, InstallationManagerNoJob(), ready=True)

    await monitor.refresh()

    assert monitor.snapshot.state == SystemStateValue.READY


@pytest.mark.asyncio
async def test_running_job_restores_updating_state() -> None:
    clock = Clock()
    monitor = _monitor(clock, _summary(clock, "running"), ready=True)

    await monitor.refresh()

    assert monitor.snapshot.state == SystemStateValue.UPDATING


@pytest.mark.asyncio
async def test_recent_succeeded_job_waits_until_services_are_ready() -> None:
    clock = Clock()
    manager = FakeManagerClient(_summary(clock, "succeeded", finished=True))
    readiness = FakeReadinessChecker(False)
    monitor = SystemStateMonitor(
        manager_client=manager,  # type: ignore[arg-type]
        readiness_checker=readiness,  # type: ignore[arg-type]
        poll_interval_sec=2,
        retry_after_sec=3,
        manager_stale_timeout_sec=60,
        readiness_timeout_sec=300,
        recent_update_window_sec=600,
        readiness_probe_timeout_sec=1,
        now=lambda: clock.now,
        monotonic=lambda: clock.monotonic,
    )

    await monitor.refresh()
    assert monitor.snapshot.state == SystemStateValue.UPDATING

    readiness.ready = True
    await monitor.refresh()
    assert monitor.snapshot.state == SystemStateValue.READY


@pytest.mark.asyncio
async def test_readiness_timeout_unblocks_as_degraded() -> None:
    clock = Clock()
    monitor = _monitor(clock, _summary(clock, "succeeded", finished=True), ready=False)

    await monitor.refresh()
    clock.advance(301)
    await monitor.refresh()
    assert monitor.snapshot.state == SystemStateValue.DEGRADED

    await monitor.refresh()
    assert monitor.snapshot.state == SystemStateValue.DEGRADED


@pytest.mark.asyncio
async def test_failed_job_is_degraded_and_not_updating() -> None:
    clock = Clock()
    monitor = _monitor(clock, _summary(clock, "failed", finished=True), ready=True)

    await monitor.refresh()

    assert monitor.snapshot.state == SystemStateValue.DEGRADED


@pytest.mark.asyncio
async def test_manager_unavailable_keeps_known_update_until_stale_timeout() -> None:
    clock = Clock()
    manager = FakeManagerClient(InstallationManagerUnavailable())
    monitor = _monitor(clock, manager.result, ready=True)

    await monitor.mark_updating("job-1")
    await monitor.refresh()
    assert monitor.snapshot.state == SystemStateValue.UPDATING

    clock.advance(61)
    await monitor.refresh()
    assert monitor.snapshot.state == SystemStateValue.DEGRADED


@pytest.mark.asyncio
async def test_running_job_reenters_updating_after_degraded() -> None:
    clock = Clock()
    manager = FakeManagerClient(InstallationManagerUnavailable())
    readiness = FakeReadinessChecker(True)
    monitor = SystemStateMonitor(
        manager_client=manager,  # type: ignore[arg-type]
        readiness_checker=readiness,  # type: ignore[arg-type]
        poll_interval_sec=2,
        retry_after_sec=3,
        manager_stale_timeout_sec=60,
        readiness_timeout_sec=300,
        recent_update_window_sec=600,
        readiness_probe_timeout_sec=1,
        now=lambda: clock.now,
        monotonic=lambda: clock.monotonic,
    )

    await monitor.refresh()
    assert monitor.snapshot.state == SystemStateValue.DEGRADED

    manager.result = _summary(clock, "running")
    await monitor.refresh()
    assert monitor.snapshot.state == SystemStateValue.UPDATING
