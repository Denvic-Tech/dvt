from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from src.clients.scheduler_client import get_schedule_client
from src.enums import DVTDefaultRoles, RetryBackoff
from src.models import OrganizationRecord
from src.modules.project.infra.db_models import ProjectRecord
from src.modules.task_execution.domain.types import TaskExecutionStatus, TaskSource
from src.modules.task_execution.infra.db_models import TaskRecord
from src.modules.user.infra.db_models import UserRecord as UserModel
from src.pipeline.execution_mode import PipelineExecutionMode
from src.schemas.http.task import ScheduleResponse
from src.schemas.internal import ProjectScheduleResponse


class _FakeSchedulerClient:
    def __init__(self) -> None:
        self.schedule_payload: dict | None = None
        self.patch_payload: dict | None = None
        self.patched_project_id: str | None = None
        self.deleted_project_id: str | None = None
        self.unscheduled_project_id: str | None = None
        self.list_organization_id: str | None = None
        self._list_response: list[ProjectScheduleResponse] = []

    async def schedule_project(self, data: dict) -> ScheduleResponse:
        self.schedule_payload = data
        return ScheduleResponse(
            success=True,
            message=f"Project scheduled with cron '{data['cron']}'",
            project_id=data["project_id"],
        )

    async def patch_project_schedule(self, project_id: str, data: dict) -> ScheduleResponse:
        self.patched_project_id = project_id
        self.patch_payload = data
        return ScheduleResponse(
            success=True,
            message="Project schedule updated",
            project_id=project_id,
        )

    async def delete_project_schedule(self, project_id: str) -> ScheduleResponse:
        self.deleted_project_id = project_id
        return ScheduleResponse(
            success=True,
            message="Project schedule deleted",
            project_id=project_id,
        )

    async def unschedule_project(self, project_id: str) -> ScheduleResponse:
        self.unscheduled_project_id = project_id
        return ScheduleResponse(
            success=True,
            message="Project unscheduled",
            project_id=project_id,
        )

    async def get_scheduled_projects(
        self,
        organization_id: str | None = None,
    ) -> list[ProjectScheduleResponse]:
        self.list_organization_id = organization_id
        return self._list_response


def _make_user(
    *,
    email: str,
    organization_id: str,
    role: str,
) -> UserModel:
    return UserModel(
        email=email,
        hashed_password="hashed",
        auth_provider="email",
        is_verified=True,
        is_active=True,
        role=role,
        organization_id=organization_id,
    )


@pytest.mark.asyncio
async def test_admin_schedule_passes_actor_to_scheduler(
    gateway_client,
    router_prefix,
    test_admin_user,
    test_admin_project,
):
    from services.gateway.main import app
    from services.gateway.routes.project import schedule as project_schedule

    fake_scheduler_client = _FakeSchedulerClient()
    app.dependency_overrides[project_schedule._get_user] = lambda: test_admin_user
    app.dependency_overrides[get_schedule_client] = lambda: fake_scheduler_client
    try:
        response = await gateway_client.post(
            f"{router_prefix}/projects/scheduler/schedule",
            json={
                "project_id": test_admin_project.id,
                "cron": "*/5 * * * *",
                "max_retries": 3,
                "retry_delay_seconds": 30,
                "retry_backoff": RetryBackoff.EXPONENTIAL.value,
                "retry_max_delay_seconds": 300,
                "next_run_time": datetime.now(tz=UTC).isoformat(),
            },
        )
    finally:
        app.dependency_overrides.pop(project_schedule._get_user, None)
        app.dependency_overrides.pop(get_schedule_client, None)

    assert response.status_code == 200, response.json()
    assert fake_scheduler_client.schedule_payload is not None
    assert fake_scheduler_client.schedule_payload["project_id"] == test_admin_project.id
    assert fake_scheduler_client.schedule_payload["scheduled_by_user_id"] == test_admin_user.id
    assert fake_scheduler_client.schedule_payload["max_retries"] == 3
    assert fake_scheduler_client.schedule_payload["retry_delay_seconds"] == 30
    assert fake_scheduler_client.schedule_payload["retry_backoff"] == RetryBackoff.EXPONENTIAL.value
    assert fake_scheduler_client.schedule_payload["retry_max_delay_seconds"] == 300
    assert "next_run_time" not in fake_scheduler_client.schedule_payload


@pytest.mark.asyncio
async def test_admin_cannot_unschedule_project_from_other_organization(
    gateway_client,
    router_prefix,
    db_session,
    test_admin_user,
):
    from services.gateway.main import app
    from services.gateway.routes.project import schedule as project_schedule

    foreign_org = OrganizationRecord(name="Foreign org")
    db_session.add(foreign_org)
    db_session.commit()
    db_session.refresh(foreign_org)

    foreign_user = _make_user(
        email="foreign-admin@example.com",
        organization_id=foreign_org.id,
        role=DVTDefaultRoles.ADMIN.value,
    )
    db_session.add(foreign_user)
    db_session.commit()
    db_session.refresh(foreign_user)

    foreign_project = ProjectRecord(
        id=str(uuid4()),
        name="Foreign project",
        user_id=foreign_user.id,
        organization_id=foreign_org.id,
    )
    db_session.add(foreign_project)
    db_session.commit()

    fake_scheduler_client = _FakeSchedulerClient()
    app.dependency_overrides[project_schedule._get_user] = lambda: test_admin_user
    app.dependency_overrides[get_schedule_client] = lambda: fake_scheduler_client
    try:
        response = await gateway_client.post(
            f"{router_prefix}/projects/scheduler/unschedule",
            params={"project_id": foreign_project.id},
        )
    finally:
        app.dependency_overrides.pop(project_schedule._get_user, None)
        app.dependency_overrides.pop(get_schedule_client, None)

    assert response.status_code == 404, response.json()
    assert fake_scheduler_client.unscheduled_project_id is None


@pytest.mark.asyncio
async def test_admin_patch_schedule_passes_actor_to_scheduler(
    gateway_client,
    router_prefix,
    test_admin_user,
    test_admin_project,
):
    from services.gateway.main import app
    from services.gateway.routes.project import schedule as project_schedule

    fake_scheduler_client = _FakeSchedulerClient()
    app.dependency_overrides[project_schedule._get_user] = lambda: test_admin_user
    app.dependency_overrides[get_schedule_client] = lambda: fake_scheduler_client
    try:
        response = await gateway_client.patch(
            f"{router_prefix}/projects/scheduler/schedule/{test_admin_project.id}",
            json={
                "cron": "15 * * * *",
                "disabled": True,
                "max_retries": 2,
                "retry_delay_seconds": 45,
                "next_run_time": datetime.now(tz=UTC).isoformat(),
            },
        )
    finally:
        app.dependency_overrides.pop(project_schedule._get_user, None)
        app.dependency_overrides.pop(get_schedule_client, None)

    assert response.status_code == 200, response.json()
    assert fake_scheduler_client.patched_project_id == test_admin_project.id
    assert fake_scheduler_client.patch_payload is not None
    assert fake_scheduler_client.patch_payload["cron"] == "15 * * * *"
    assert fake_scheduler_client.patch_payload["disabled"] is True
    assert fake_scheduler_client.patch_payload["scheduled_by_user_id"] == test_admin_user.id
    assert fake_scheduler_client.patch_payload["max_retries"] == 2
    assert fake_scheduler_client.patch_payload["retry_delay_seconds"] == 45
    assert "next_run_time" not in fake_scheduler_client.patch_payload


@pytest.mark.asyncio
async def test_admin_delete_schedule_passes_project_to_scheduler(
    gateway_client,
    router_prefix,
    test_admin_user,
    test_admin_project,
):
    from services.gateway.main import app
    from services.gateway.routes.project import schedule as project_schedule

    fake_scheduler_client = _FakeSchedulerClient()
    app.dependency_overrides[project_schedule._get_user] = lambda: test_admin_user
    app.dependency_overrides[get_schedule_client] = lambda: fake_scheduler_client
    try:
        response = await gateway_client.delete(
            f"{router_prefix}/projects/scheduler/schedule/{test_admin_project.id}",
        )
    finally:
        app.dependency_overrides.pop(project_schedule._get_user, None)
        app.dependency_overrides.pop(get_schedule_client, None)

    assert response.status_code == 200, response.json()
    assert fake_scheduler_client.deleted_project_id == test_admin_project.id


@pytest.mark.asyncio
async def test_admin_cannot_delete_schedule_from_other_organization(
    gateway_client,
    router_prefix,
    db_session,
    test_admin_user,
):
    from services.gateway.main import app
    from services.gateway.routes.project import schedule as project_schedule

    foreign_org = OrganizationRecord(name="Foreign org for delete")
    db_session.add(foreign_org)
    db_session.commit()
    db_session.refresh(foreign_org)

    foreign_user = _make_user(
        email="foreign-delete-admin@example.com",
        organization_id=foreign_org.id,
        role=DVTDefaultRoles.ADMIN.value,
    )
    db_session.add(foreign_user)
    db_session.commit()
    db_session.refresh(foreign_user)

    foreign_project = ProjectRecord(
        id=str(uuid4()),
        name="Foreign project delete",
        user_id=foreign_user.id,
        organization_id=foreign_org.id,
    )
    db_session.add(foreign_project)
    db_session.commit()

    fake_scheduler_client = _FakeSchedulerClient()
    app.dependency_overrides[project_schedule._get_user] = lambda: test_admin_user
    app.dependency_overrides[get_schedule_client] = lambda: fake_scheduler_client
    try:
        response = await gateway_client.delete(
            f"{router_prefix}/projects/scheduler/schedule/{foreign_project.id}",
        )
    finally:
        app.dependency_overrides.pop(project_schedule._get_user, None)
        app.dependency_overrides.pop(get_schedule_client, None)

    assert response.status_code == 404, response.json()
    assert fake_scheduler_client.deleted_project_id is None


@pytest.mark.asyncio
async def test_get_scheduled_projects_filters_by_admin_organization(
    gateway_client,
    router_prefix,
    test_admin_user,
):
    from services.gateway.main import app
    from services.gateway.routes.project import schedule as project_schedule

    fake_scheduler_client = _FakeSchedulerClient()
    fake_scheduler_client._list_response = [
        ProjectScheduleResponse(
            project_id=str(uuid4()),
            cron="0 * * * *",
            disabled=False,
            scheduled_by_user_id=test_admin_user.id,
        )
    ]
    app.dependency_overrides[project_schedule._get_user] = lambda: test_admin_user
    app.dependency_overrides[get_schedule_client] = lambda: fake_scheduler_client
    try:
        response = await gateway_client.get(f"{router_prefix}/projects/scheduler/scheduled")
    finally:
        app.dependency_overrides.pop(project_schedule._get_user, None)
        app.dependency_overrides.pop(get_schedule_client, None)

    assert response.status_code == 200, response.json()
    assert fake_scheduler_client.list_organization_id == test_admin_user.organization_id


@pytest.mark.asyncio
async def test_get_scheduled_projects_includes_scheduler_run_history(
    gateway_client,
    router_prefix,
    db_session,
    test_admin_user,
    test_admin_project,
):
    from services.gateway.main import app
    from services.gateway.routes.project import schedule as project_schedule

    fake_scheduler_client = _FakeSchedulerClient()
    fake_scheduler_client._list_response = [
        ProjectScheduleResponse(
            project_id=test_admin_project.id,
            cron="0 * * * *",
            disabled=False,
            scheduled_by_user_id=test_admin_user.id,
        )
    ]

    first_queued_at = datetime(2026, 5, 5, 9, 0, tzinfo=UTC)
    last_started_at = datetime(2026, 5, 6, 11, 30, tzinfo=UTC)
    scheduler_runs = [
        TaskRecord(
            task_id="scheduler-run-1",
            mode=PipelineExecutionMode.FULL,
            status=TaskExecutionStatus.SUCCESS,
            source=TaskSource.SCHEDULER.value,
            queued_at=first_queued_at,
            started_at=first_queued_at + timedelta(minutes=1),
            finished_at=first_queued_at + timedelta(minutes=3),
            message="Run finished successfully",
            user_id=test_admin_user.id,
            organization_id=test_admin_user.organization_id,
            project_id=test_admin_project.id,
        ),
        TaskRecord(
            task_id="scheduler-run-2",
            mode=PipelineExecutionMode.FULL,
            status=TaskExecutionStatus.ERROR,
            source=TaskSource.SCHEDULER.value,
            queued_at=last_started_at - timedelta(minutes=2),
            started_at=last_started_at,
            finished_at=last_started_at + timedelta(minutes=4),
            message="Validation error: broken node",
            termination_reason="NODE_FAILURE",
            user_id=test_admin_user.id,
            organization_id=test_admin_user.organization_id,
            project_id=test_admin_project.id,
        ),
        TaskRecord(
            task_id="scheduler-metadata-run",
            mode=PipelineExecutionMode.METADATA_ONLY,
            status=TaskExecutionStatus.SUCCESS,
            source=TaskSource.SCHEDULER.value,
            queued_at=last_started_at - timedelta(minutes=5),
            started_at=last_started_at - timedelta(minutes=4),
            finished_at=last_started_at - timedelta(minutes=3),
            message="Metadata scheduler run",
            user_id=test_admin_user.id,
            organization_id=test_admin_user.organization_id,
            project_id=test_admin_project.id,
        ),
        TaskRecord(
            task_id="ui-run-ignored",
            mode=PipelineExecutionMode.FULL,
            status=TaskExecutionStatus.SUCCESS,
            source=TaskSource.UI.value,
            queued_at=last_started_at + timedelta(minutes=10),
            started_at=last_started_at + timedelta(minutes=11),
            finished_at=last_started_at + timedelta(minutes=12),
            message="UI run should not leak into scheduler history",
            user_id=test_admin_user.id,
            organization_id=test_admin_user.organization_id,
            project_id=test_admin_project.id,
        ),
    ]
    db_session.add_all(scheduler_runs)
    db_session.commit()

    app.dependency_overrides[project_schedule._get_user] = lambda: test_admin_user
    app.dependency_overrides[get_schedule_client] = lambda: fake_scheduler_client
    try:
        response = await gateway_client.get(f"{router_prefix}/projects/scheduler/scheduled")
    finally:
        app.dependency_overrides.pop(project_schedule._get_user, None)
        app.dependency_overrides.pop(get_schedule_client, None)

    assert response.status_code == 200, response.json()
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["last_run_task_id"] == "scheduler-run-2"
    assert payload[0]["last_run_status"] == TaskExecutionStatus.ERROR.value
    assert (
        datetime.fromisoformat(payload[0]["last_run_time"].replace("Z", "+00:00"))
        == last_started_at
    )
    assert payload[0]["last_run_message"] == "Validation error: broken node"
    assert payload[0]["last_run_termination_reason"] == "NODE_FAILURE"
    assert [run["task_id"] for run in payload[0]["recent_runs"]] == [
        "scheduler-run-2",
        "scheduler-metadata-run",
        "scheduler-run-1",
    ]
    assert all(run["task_id"] != "ui-run-ignored" for run in payload[0]["recent_runs"])


@pytest.mark.asyncio
async def test_get_scheduled_projects_uses_global_scope_for_superadmin(
    gateway_client,
    router_prefix,
    db_session,
    test_organization,
):
    from services.gateway.main import app
    from services.gateway.routes.project import schedule as project_schedule

    superadmin_user = _make_user(
        email="superadmin@example.com",
        organization_id=test_organization.id,
        role=DVTDefaultRoles.SUPERADMIN.value,
    )
    db_session.add(superadmin_user)
    db_session.commit()
    db_session.refresh(superadmin_user)

    fake_scheduler_client = _FakeSchedulerClient()
    app.dependency_overrides[project_schedule._get_user] = lambda: superadmin_user
    app.dependency_overrides[get_schedule_client] = lambda: fake_scheduler_client
    try:
        response = await gateway_client.get(f"{router_prefix}/projects/scheduler/scheduled")
    finally:
        app.dependency_overrides.pop(project_schedule._get_user, None)
        app.dependency_overrides.pop(get_schedule_client, None)

    assert response.status_code == 200, response.json()
    assert fake_scheduler_client.list_organization_id is None
