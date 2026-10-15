from __future__ import annotations

import asyncio

import pytest

from services.gateway.deps.clients import get_orchestrator_client
from services.gateway.routes.widgets import impl as widgets_impl

from src.clients.scheduler_client import get_schedule_client
from src.enums import WorkerStatus
from src.schemas.http.system import SystemInfo, WorkerSystemInfo


def _system_info(**overrides) -> dict:
    payload = {
        "hostname": "svc-host",
        "os_type": "Linux",
        "os_release": "6.1",
        "os_version": "#1",
        "system_uptime_seconds": 1000.0,
        "app_uptime_seconds": 120.0,
        "cpu_percent": 1.0,
        "cpu_cores_physical": 2,
        "cpu_cores_logical": 4,
        "ram_total": 8.0,
        "ram_available": 4.0,
        "ram_used": 4.0,
        "ram_used_percent": 50.0,
        "disk_total": 100.0,
        "disk_used": 50.0,
        "disk_free": 50.0,
        "disk_used_percent": 50.0,
        "network_bytes_sent": 1,
        "network_bytes_recv": 1,
        "process_count": 10,
    }
    payload.update(overrides)
    return payload


def _worker(worker_id: str, *, status: WorkerStatus = WorkerStatus.ONLINE, busy: bool = False) -> WorkerSystemInfo:
    return WorkerSystemInfo(**_system_info(), worker_id=worker_id, status=status, has_running_task=busy)


class _FakeOrchestrator:
    def __init__(self, workers=None, *, error: Exception | None = None, delay: float = 0.0):
        self.workers = workers or []
        self.error = error
        self.delay = delay

    async def get_system_stats(self):
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return list(self.workers)


class _FakeScheduler:
    def __init__(self, *, error: Exception | None = None, delay: float = 0.0):
        self.error = error
        self.delay = delay

    async def system_status(self):
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return SystemInfo(**_system_info(app_uptime_seconds=300.0))


@pytest.fixture
def override_clients(gateway_client):
    from services.gateway.main import app

    def _set(orchestrator, scheduler) -> None:
        app.dependency_overrides[get_orchestrator_client] = lambda: orchestrator
        app.dependency_overrides[get_schedule_client] = lambda: scheduler

    yield _set
    app.dependency_overrides.pop(get_orchestrator_client, None)
    app.dependency_overrides.pop(get_schedule_client, None)


@pytest.mark.asyncio
async def test_services_requires_admin(gateway_client, router_prefix, override_clients):
    override_clients(_FakeOrchestrator(), _FakeScheduler())

    resp = await gateway_client.get(f"{router_prefix}/widgets/services")

    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_services_reports_online_services_and_workers(
        gateway_client,
        router_prefix,
        test_admin_user,
        set_current_user,
        override_clients,
):
    set_current_user(test_admin_user)
    override_clients(
        _FakeOrchestrator([
            _worker("w1", busy=True),
            _worker("w2"),
            _worker("w3", status=WorkerStatus.OFFLINE),
        ]),
        _FakeScheduler(),
    )

    resp = await gateway_client.get(f"{router_prefix}/widgets/services")

    assert resp.status_code == 200, resp.json()
    payload = resp.json()
    services = {item["name"]: item for item in payload["services"]}
    assert set(services) == {"gateway", "project_scheduler", "orchestrator"}
    assert services["gateway"]["status"] == "online"
    assert services["gateway"]["latency_ms"] is None
    assert services["project_scheduler"]["status"] == "online"
    assert services["project_scheduler"]["latency_ms"] is not None
    assert services["project_scheduler"]["uptime_seconds"] == 300.0
    assert services["orchestrator"]["status"] == "online"
    assert services["orchestrator"]["latency_ms"] is not None
    assert payload["workers"] == {"total": 3, "online": 2, "busy": 1}
    assert payload["system_state"] in {"ready", "updating", "degraded"}
    assert "hostname" not in resp.text


@pytest.mark.asyncio
async def test_services_marks_failing_and_slow_services_offline(
        gateway_client,
        router_prefix,
        test_admin_user,
        set_current_user,
        override_clients,
        monkeypatch,
):
    set_current_user(test_admin_user)
    monkeypatch.setattr(widgets_impl, "SERVICE_CALL_TIMEOUT_SEC", 0.05)
    override_clients(
        _FakeOrchestrator(error=RuntimeError("grpc down")),
        _FakeScheduler(delay=0.3),
    )

    resp = await gateway_client.get(f"{router_prefix}/widgets/services")

    assert resp.status_code == 200, resp.json()
    payload = resp.json()
    services = {item["name"]: item for item in payload["services"]}
    assert services["orchestrator"]["status"] == "offline"
    assert services["orchestrator"]["latency_ms"] is None
    assert services["project_scheduler"]["status"] == "offline"
    assert services["project_scheduler"]["uptime_seconds"] is None
    assert payload["workers"] == {"total": 0, "online": 0, "busy": 0}
