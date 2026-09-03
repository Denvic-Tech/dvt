from datetime import UTC, datetime
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException

from services.gateway.routes import system as system_route
from services.gateway.routes.installation import update as update_route
from services.gateway.update_runtime.monitor import SystemStateSnapshot

from src.schemas.http.system import SystemStateValue
from src.schemas.http.update import UpdateRequestSchema


class FakeMonitor:
    def __init__(self) -> None:
        self.snapshot = SystemStateSnapshot(
            state=SystemStateValue.UPDATING,
            retry_after_sec=3,
            checked_at=datetime(2026, 7, 22, tzinfo=UTC),
        )
        self.mark_updating = AsyncMock()


@pytest.mark.asyncio
async def test_system_state_returns_public_snapshot(monkeypatch) -> None:
    monitor = FakeMonitor()
    monkeypatch.setattr(system_route, "get_system_state_monitor", lambda: monitor)

    response = await system_route.get_system_state()

    assert response.state == SystemStateValue.UPDATING
    assert response.retry_after_sec == 3
    assert response.checked_at == monitor.snapshot.checked_at


@pytest.mark.asyncio
async def test_run_update_marks_system_updating_after_manager_accepts(monkeypatch) -> None:
    monitor = FakeMonitor()
    manager_response = httpx.Response(
        202,
        json={
            "success": True,
            "message": "Update started",
            "version": "latest",
            "job_id": "job-1",
        },
    )
    monkeypatch.setattr(
        update_route,
        "_installation_manager_request",
        AsyncMock(return_value=manager_response),
    )
    monkeypatch.setattr(update_route, "get_system_state_monitor", lambda: monitor)

    result = await update_route.run_update(UpdateRequestSchema(version="latest"), None)

    assert result.job_id == "job-1"
    monitor.mark_updating.assert_awaited_once_with("job-1")


@pytest.mark.asyncio
async def test_run_update_does_not_mark_system_when_manager_rejects(monkeypatch) -> None:
    monitor = FakeMonitor()
    monkeypatch.setattr(
        update_route,
        "_installation_manager_request",
        AsyncMock(side_effect=HTTPException(status_code=409, detail="already running")),
    )
    monkeypatch.setattr(update_route, "get_system_state_monitor", lambda: monitor)

    with pytest.raises(HTTPException) as exc_info:
        await update_route.run_update(UpdateRequestSchema(version="latest"), None)

    assert exc_info.value.status_code == 409
    monitor.mark_updating.assert_not_awaited()
