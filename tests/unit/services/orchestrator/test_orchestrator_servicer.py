from __future__ import annotations

import orjson
import pytest

from services.orchestrator.execution_registry import TaskExecutionRecord, TaskExecutionRegistry
from services.orchestrator.servicers.orchestrator import OrchestratorServicer

from src.schemas.http.system import SystemInfo


class _FakeWorkerRegistry:
    def __init__(self, workers):
        self._workers = workers

    def get_alive_workers(self, _now_ts):
        return self._workers

    def all(self):
        return self._workers


class _FakeWorkerState:
    def __init__(
            self,
            *,
            worker_id: str,
            max_concurrent: int,
            status: str,
            alive: bool,
            capabilities,
            system_info: SystemInfo | None = None,
            timestamp: float = 995.0,
            first_seen_at: float = 900.0,
            last_received_at: float = 995.0,
            last_status_change_at: float = 995.0,
            offline_since: float | None = None,
            availability_reported: bool = False,
            is_busy: bool = False,
            available_slots: int | None = None,
    ):
        self.worker_id = worker_id
        self.max_concurrent = max_concurrent
        self.status = status
        self.capabilities = capabilities
        self._alive = alive
        self.system_info = system_info
        self.timestamp = timestamp
        self.first_seen_at = first_seen_at
        self.last_received_at = last_received_at
        self.last_status_change_at = last_status_change_at
        self.offline_since = offline_since
        self.availability_reported = availability_reported
        self.is_busy = is_busy
        self.available_slots = max_concurrent if available_slots is None else available_slots

    def is_alive(self, _now_ts, _heartbeat_timeout_sec):
        return self._alive


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
async def test_get_system_stats_includes_running_task_memory(monkeypatch):
    execution_registry = TaskExecutionRegistry()
    await execution_registry.upsert(
        TaskExecutionRecord(
            task_id="task-1",
            worker_id="worker-1",
            hostname="host-1",
            pid=123,
            rss_bytes=250,
            memory_limit_bytes=1_000,
            system_ram_used_percent=80.0,
            timestamp=1_000.0,
        )
    )

    workers = [
        _FakeWorkerState(
            worker_id="worker-1",
            max_concurrent=1,
            status="online",
            alive=True,
            capabilities=["full", "metadata_only"],
            system_info=_make_system_info("host-1"),
            timestamp=998.0,
            first_seen_at=900.0,
            last_received_at=999.0,
            last_status_change_at=999.0,
        ),
        _FakeWorkerState(
            worker_id="worker-2",
            max_concurrent=1,
            status="offline",
            alive=False,
            capabilities=["full"],
            system_info=_make_system_info("host-2"),
            timestamp=980.0,
            first_seen_at=850.0,
            last_received_at=990.0,
            last_status_change_at=995.0,
            offline_since=995.0,
        ),
    ]

    monkeypatch.setattr(
        "services.orchestrator.servicers.orchestrator.get_worker_registry",
        lambda: _FakeWorkerRegistry(workers),
    )
    monkeypatch.setattr(
        "services.orchestrator.servicers.orchestrator.get_task_execution_registry",
        lambda: execution_registry,
    )
    monkeypatch.setattr(
        "services.orchestrator.servicers.orchestrator.time.time",
        lambda: 1_000.0,
    )

    response = await OrchestratorServicer().GetSystemStats(request=None, context=None)
    payload = orjson.loads(response.system_infos_json)

    assert payload == [
        {
            "worker_id": "worker-1",
            "status": "online",
            "first_seen_at": 900.0,
            "last_heartbeat_at": 998.0,
            "last_heartbeat_received_at": 999.0,
            "last_status_change_at": 999.0,
            "offline_since": None,
            "heartbeat_age_sec": 1.0,
            "hostname": "host-1",
            "os_type": "Linux",
            "os_release": "6.8",
            "os_version": "test",
            "system_uptime_seconds": 100.0,
            "app_uptime_seconds": 50.0,
            "cpu_percent": 10.0,
            "cpu_cores_physical": 4,
            "cpu_cores_logical": 8,
            "ram_total": 1000.0,
            "ram_available": 400.0,
            "ram_used": 600.0,
            "ram_used_percent": 60.0,
            "disk_total": 2000.0,
            "disk_used": 500.0,
            "disk_free": 1500.0,
            "disk_used_percent": 25.0,
            "network_bytes_sent": 100,
            "network_bytes_recv": 200,
            "process_count": 42,
            "has_running_task": True,
            "running_task_ram_used": 250.0,
            "running_task_ram_used_percent": 25.0,
        },
        {
            "worker_id": "worker-2",
            "status": "offline",
            "first_seen_at": 850.0,
            "last_heartbeat_at": 980.0,
            "last_heartbeat_received_at": 990.0,
            "last_status_change_at": 995.0,
            "offline_since": 995.0,
            "heartbeat_age_sec": 10.0,
            "hostname": "host-2",
            "os_type": "Linux",
            "os_release": "6.8",
            "os_version": "test",
            "system_uptime_seconds": 100.0,
            "app_uptime_seconds": 50.0,
            "cpu_percent": 10.0,
            "cpu_cores_physical": 4,
            "cpu_cores_logical": 8,
            "ram_total": 1000.0,
            "ram_available": 400.0,
            "ram_used": 600.0,
            "ram_used_percent": 60.0,
            "disk_total": 2000.0,
            "disk_used": 500.0,
            "disk_free": 1500.0,
            "disk_used_percent": 25.0,
            "network_bytes_sent": 100,
            "network_bytes_recv": 200,
            "process_count": 42,
            "has_running_task": False,
            "running_task_ram_used": None,
            "running_task_ram_used_percent": None,
        },
    ]


@pytest.mark.asyncio
async def test_get_execution_capacity_uses_busy_heartbeat_without_telemetry_after_restart(monkeypatch):
    execution_registry = TaskExecutionRegistry()
    workers = [
        _FakeWorkerState(
            worker_id="worker-1",
            max_concurrent=1,
            status="online",
            alive=True,
            capabilities=["full"],
            availability_reported=True,
            is_busy=True,
            available_slots=0,
        ),
        _FakeWorkerState(
            worker_id="worker-2",
            max_concurrent=1,
            status="online",
            alive=True,
            capabilities=["full"],
            availability_reported=True,
            is_busy=False,
            available_slots=1,
        ),
    ]
    monkeypatch.setattr(
        "services.orchestrator.servicers.orchestrator.get_worker_registry",
        lambda: _FakeWorkerRegistry(workers),
    )
    monkeypatch.setattr(
        "services.orchestrator.servicers.orchestrator.get_task_execution_registry",
        lambda: execution_registry,
    )
    monkeypatch.setattr(
        "services.orchestrator.servicers.orchestrator.time.time",
        lambda: 1_000.0,
    )

    response = await OrchestratorServicer().GetExecutionCapacity(request=None, context=None)

    assert response.total_capacity == 2
    assert response.busy_capacity == 1
    assert response.available_capacity == 1
    assert [(item.worker_id, item.busy, item.available_slots) for item in response.workers] == [
        ("worker-1", True, 0),
        ("worker-2", False, 1),
    ]


@pytest.mark.asyncio
async def test_get_execution_capacity_returns_alive_capacity_snapshot(monkeypatch):
    workers = [
        _FakeWorkerState(
            worker_id="worker-1",
            max_concurrent=2,
            status="online",
            alive=True,
            capabilities=["full", "metadata_only"],
        ),
        _FakeWorkerState(
            worker_id="worker-2",
            max_concurrent=1,
            status="online",
            alive=True,
            capabilities=["full"],
        ),
        _FakeWorkerState(
            worker_id="worker-3",
            max_concurrent=10,
            status="offline",
            alive=False,
            capabilities=["full"],
        ),
    ]

    monkeypatch.setattr(
        "services.orchestrator.servicers.orchestrator.get_worker_registry",
        lambda: _FakeWorkerRegistry(workers),
    )
    monkeypatch.setattr(
        "services.orchestrator.servicers.orchestrator.time.time",
        lambda: 1_000.0,
    )

    response = await OrchestratorServicer().GetExecutionCapacity(request=None, context=None)

    assert response.alive_workers_count == 2
    assert response.total_capacity == 3
    assert response.busy_capacity == 0
    assert response.available_capacity == 3
    assert [
        {
            "worker_id": item.worker_id,
            "max_concurrent": item.max_concurrent,
            "status": item.status,
            "alive": item.alive,
            "capabilities": list(item.capabilities),
            "busy": item.busy,
            "available_slots": item.available_slots,
        }
        for item in response.workers
    ] == [
        {
            "worker_id": "worker-1",
            "max_concurrent": 2,
            "status": "online",
            "alive": True,
            "capabilities": ["full", "metadata_only"],
            "busy": False,
            "available_slots": 2,
        },
        {
            "worker_id": "worker-2",
            "max_concurrent": 1,
            "status": "online",
            "alive": True,
            "capabilities": ["full"],
            "busy": False,
            "available_slots": 1,
        },
        {
            "worker_id": "worker-3",
            "max_concurrent": 10,
            "status": "offline",
            "alive": False,
            "capabilities": ["full"],
            "busy": False,
            "available_slots": 0,
        },
    ]
