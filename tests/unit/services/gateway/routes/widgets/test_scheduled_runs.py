from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.clients.scheduler_client import get_schedule_client
from src.modules.task_execution.domain.types import TaskExecutionStatus, TaskSource
from src.schemas.internal import ProjectScheduleResponse

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)


class _FakeSchedulerClient:
    def __init__(self, schedules: list[ProjectScheduleResponse]):
        self.schedules = schedules
        self.calls: list[str | None] = []

    async def get_scheduled_projects(self, organization_id: str | None = None):
        self.calls.append(organization_id)
        return list(self.schedules)


@pytest.fixture
def fake_scheduler(gateway_client):
    from services.gateway.main import app

    client = _FakeSchedulerClient([])
    app.dependency_overrides[get_schedule_client] = lambda: client
    yield client
    app.dependency_overrides.pop(get_schedule_client, None)


def _schedule(project_id: str, *, next_run_time: datetime | None, disabled: bool = False) -> ProjectScheduleResponse:
    return ProjectScheduleResponse(
        project_id=project_id,
        cron="0 * * * *",
        disabled=disabled,
        next_run_time=next_run_time,
    )


@pytest.mark.asyncio
async def test_scheduled_runs_requires_admin(gateway_client, router_prefix, fake_scheduler):
    resp = await gateway_client.get(f"{router_prefix}/widgets/scheduled-runs")

    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_scheduled_runs_orders_filters_and_limits(
        gateway_client,
        router_prefix,
        test_admin_user,
        create_project,
        add_task,
        set_current_user,
        fake_scheduler,
):
    set_current_user(test_admin_user)
    later = create_project(user=test_admin_user, name="Later")
    sooner = create_project(user=test_admin_user, name="Sooner")
    disabled = create_project(user=test_admin_user, name="Disabled")
    deleted = create_project(user=test_admin_user, name="Deleted", is_deleted=True)
    third = create_project(user=test_admin_user, name="Third")
    fake_scheduler.schedules = [
        _schedule(later.id, next_run_time=NOW + timedelta(hours=2)),
        _schedule(sooner.id, next_run_time=NOW + timedelta(minutes=30)),
        _schedule(disabled.id, next_run_time=NOW + timedelta(minutes=5), disabled=True),
        _schedule(deleted.id, next_run_time=NOW + timedelta(minutes=1)),
        _schedule(third.id, next_run_time=NOW + timedelta(hours=3)),
        _schedule("unknown-project", next_run_time=NOW),
    ]
    add_task(
        user=test_admin_user,
        project=sooner,
        queued_at=NOW - timedelta(hours=1),
        status=TaskExecutionStatus.ERROR,
        source=TaskSource.SCHEDULER,
        started_at=NOW - timedelta(minutes=59),
    )
    add_task(user=test_admin_user, project=sooner, queued_at=NOW - timedelta(hours=2), source=TaskSource.UI)

    resp = await gateway_client.get(f"{router_prefix}/widgets/scheduled-runs", params={"limit": 2})

    assert resp.status_code == 200, resp.json()
    payload = resp.json()
    assert fake_scheduler.calls == [test_admin_user.organization_id]
    assert payload["total_schedules"] == 4
    assert payload["disabled_schedules"] == 1
    assert [item["project_name"] for item in payload["items"]] == ["Sooner", "Later"]
    sooner_item = payload["items"][0]
    assert sooner_item["cron"] == "0 * * * *"
    assert sooner_item["last_run_status"] == TaskExecutionStatus.ERROR.value
    assert datetime.fromisoformat(sooner_item["last_run_time"]) == NOW - timedelta(minutes=59)
    assert payload["items"][1]["last_run_status"] is None


@pytest.mark.asyncio
async def test_scheduled_runs_superadmin_queries_all_organizations(
        gateway_client,
        router_prefix,
        test_superadmin_user,
        set_current_user,
        fake_scheduler,
):
    set_current_user(test_superadmin_user)

    resp = await gateway_client.get(f"{router_prefix}/widgets/scheduled-runs")

    assert resp.status_code == 200
    assert fake_scheduler.calls == [None]
    assert resp.json()["items"] == []
