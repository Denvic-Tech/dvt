from __future__ import annotations

import pytest

from services.orchestrator.worker_registry import WorkerRegistry

from src.enums import WorkerStatus
from src.pipeline.execution_mode import PipelineExecutionMode
from src.schemas.http.system import SystemInfo

import config


def _make_system_info(hostname: str) -> SystemInfo:
    return SystemInfo(
        hostname=hostname,
        os_type="Linux",
        os_release="6.8",
        os_version="test",
        system_uptime_seconds=100.0,
        app_uptime_seconds=50.0,
        cpu_percent=10.0,
        cpu_cores_physical=4,
        cpu_cores_logical=8,
        ram_total=1_000.0,
        ram_available=400.0,
        ram_used=600.0,
        ram_used_percent=60.0,
        disk_total=2_000.0,
        disk_used=500.0,
        disk_free=1_500.0,
        disk_used_percent=25.0,
        network_bytes_sent=100,
        network_bytes_recv=200,
        process_count=42,
    )


@pytest.mark.asyncio
async def test_reap_dead_workers_uses_last_received_at_not_payload_timestamp():
    registry = WorkerRegistry()
    timeout_sec = config.ORCHESTRATOR.ORCHESTRATOR_HEARTBEAT_TIMEOUT_SEC
    worker = await registry.update_from_heartbeat(
        worker_id="worker-1",
        capabilities={PipelineExecutionMode.FULL},
        max_concurrent=1,
        timestamp=1_000.0,
        received_at=1_000.0,
        system_info=_make_system_info("host-1"),
    )

    worker.timestamp = 1_010.0
    worker.last_received_at = 1_000.0

    dead_workers = registry.reap_dead_workers(now_ts=1_000.0 + timeout_sec + 1)

    assert [item.worker_id for item in dead_workers] == ["worker-1"]
    assert worker.status == WorkerStatus.OFFLINE
    assert worker.offline_since == 1_000.0 + timeout_sec + 1


@pytest.mark.asyncio
async def test_update_from_heartbeat_restores_offline_worker():
    registry = WorkerRegistry()
    timeout_sec = config.ORCHESTRATOR.ORCHESTRATOR_HEARTBEAT_TIMEOUT_SEC
    worker = await registry.update_from_heartbeat(
        worker_id="worker-1",
        capabilities={PipelineExecutionMode.FULL},
        max_concurrent=1,
        timestamp=1_000.0,
        received_at=1_000.0,
        system_info=_make_system_info("host-1"),
    )
    registry.reap_dead_workers(now_ts=1_000.0 + timeout_sec + 1)

    restored = await registry.update_from_heartbeat(
        worker_id="worker-1",
        capabilities={PipelineExecutionMode.FULL, PipelineExecutionMode.METADATA_ONLY},
        max_concurrent=2,
        timestamp=1_007.0,
        received_at=1_007.5,
        system_info=_make_system_info("host-1"),
    )

    assert restored.status == WorkerStatus.ONLINE
    assert restored.offline_since is None
    assert restored.last_received_at == 1_007.5
    assert restored.max_concurrent == 2
    assert restored.capabilities == {PipelineExecutionMode.FULL, PipelineExecutionMode.METADATA_ONLY}


@pytest.mark.asyncio
async def test_busy_heartbeat_restores_execution_availability_after_orchestrator_restart():
    registry = WorkerRegistry()
    worker = await registry.update_from_heartbeat(
        worker_id="worker-1",
        capabilities={PipelineExecutionMode.FULL},
        max_concurrent=1,
        timestamp=1_000.0,
        received_at=1_000.0,
        active_task_id="task-running",
        is_busy=True,
        available_slots=0,
        system_info=_make_system_info("host-1"),
    )

    assert worker.availability_reported is True
    assert worker.is_busy is True
    assert worker.active_task_id == "task-running"
    assert worker.available_slots == 0

    worker = await registry.update_from_heartbeat(
        worker_id="worker-1",
        capabilities={PipelineExecutionMode.FULL},
        max_concurrent=1,
        timestamp=1_002.0,
        received_at=1_002.0,
        active_task_id=None,
        is_busy=False,
        available_slots=1,
        system_info=_make_system_info("host-1"),
    )

    assert worker.is_busy is False
    assert worker.active_task_id is None
    assert worker.available_slots == 1


@pytest.mark.asyncio
async def test_worker_registry_tracks_busy_idle_and_offline_availability():
    registry = WorkerRegistry()
    worker = await registry.update_from_heartbeat(
        worker_id="worker-1",
        capabilities={PipelineExecutionMode.FULL},
        max_concurrent=1,
        timestamp=1_000.0,
        received_at=1_000.0,
        system_info=_make_system_info("host-1"),
    )

    assert worker.is_busy is False
    assert worker.active_task_id is None
    assert worker.available_slots == 1

    registry.mark_busy(worker_id="worker-1", task_id="task-1")
    assert worker.is_busy is True
    assert worker.active_task_id == "task-1"
    assert worker.available_slots == 0

    registry.mark_idle(worker_id="worker-1", task_id="task-1")
    assert worker.is_busy is False
    assert worker.active_task_id is None
    assert worker.available_slots == 1

    registry.mark_busy(worker_id="worker-1", task_id="task-2")
    registry.reap_dead_workers(
        now_ts=1_000.0 + config.ORCHESTRATOR.ORCHESTRATOR_HEARTBEAT_TIMEOUT_SEC + 1
    )
    assert worker.status == WorkerStatus.OFFLINE
    assert worker.is_busy is False
    assert worker.active_task_id is None
    assert worker.available_slots == 0
