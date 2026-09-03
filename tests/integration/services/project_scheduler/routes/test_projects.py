from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from apscheduler.triggers.cron import CronTrigger
from httpx import ASGITransport, AsyncClient

from services.project_scheduler.deps import get_project_scheduler_manager
from services.project_scheduler.main import app

from src.enums import RetryBackoff
from src.pipeline.execution_mode import PipelineExecutionMode
from src.schemas.internal.project_scheduler import (
    ProjectSchedulePatchRequest,
    ProjectScheduleResponse,
)

pytestmark = [pytest.mark.asyncio]


class _FakeProjectSchedulerManager:
    def __init__(self) -> None:
        self._jobs: dict[str, ProjectScheduleResponse] = {}

    async def schedule_project(
        self,
        project_id: str,
        cron: str,
        scheduled_by_user_id: str,
        mode: PipelineExecutionMode = PipelineExecutionMode.FULL,
        force_exec: bool = False,
        max_retries: int = 0,
        retry_delay_seconds: int = 60,
        retry_backoff: RetryBackoff = RetryBackoff.FIXED,
        retry_max_delay_seconds: int = 3600,
        **_kwargs,
    ) -> None:
        CronTrigger.from_crontab(cron, timezone="UTC")
        self._jobs[project_id] = ProjectScheduleResponse(
            project_id=project_id,
            cron=cron,
            disabled=False,
            scheduled_by_user_id=scheduled_by_user_id,
            next_run_time=None,
            mode=mode,
            force_exec=force_exec,
            max_retries=max_retries,
            retry_delay_seconds=retry_delay_seconds,
            retry_backoff=retry_backoff,
            retry_max_delay_seconds=retry_max_delay_seconds,
            task_id=project_id,
        )

    async def patch_project_schedule(
        self,
        project_id: str,
        patch: ProjectSchedulePatchRequest,
        **_kwargs,
    ) -> None:
        schedule = self._jobs.get(project_id)
        if schedule is None:
            raise ValueError(f"Schedule for project {project_id} not found")

        fields_set = patch.model_fields_set
        if "cron" in fields_set and patch.cron is not None:
            CronTrigger.from_crontab(patch.cron, timezone="UTC")
            schedule.cron = patch.cron
        if "scheduled_by_user_id" in fields_set and patch.scheduled_by_user_id is not None:
            schedule.scheduled_by_user_id = patch.scheduled_by_user_id
        if "mode" in fields_set and patch.mode is not None:
            schedule.mode = patch.mode
        if "force_exec" in fields_set and patch.force_exec is not None:
            schedule.force_exec = patch.force_exec
        if "max_retries" in fields_set and patch.max_retries is not None:
            schedule.max_retries = patch.max_retries
        if "retry_delay_seconds" in fields_set and patch.retry_delay_seconds is not None:
            schedule.retry_delay_seconds = patch.retry_delay_seconds
        if "retry_backoff" in fields_set and patch.retry_backoff is not None:
            schedule.retry_backoff = patch.retry_backoff
        if "retry_max_delay_seconds" in fields_set and patch.retry_max_delay_seconds is not None:
            schedule.retry_max_delay_seconds = patch.retry_max_delay_seconds
        if "disabled" in fields_set and patch.disabled is not None:
            schedule.disabled = patch.disabled
            schedule.task_id = None if patch.disabled else project_id
            if patch.disabled:
                schedule.next_run_time = None
        elif not schedule.disabled:
            schedule.task_id = project_id

    async def unschedule_project(self, project_id: str, **_kwargs) -> None:
        schedule = self._jobs.get(project_id)
        if schedule is None:
            return

        schedule.disabled = True
        schedule.task_id = None
        schedule.next_run_time = None

    async def delete_project_schedule(self, project_id: str, **_kwargs) -> None:
        if project_id not in self._jobs:
            raise ValueError(f"Schedule for project {project_id} not found")

        self._jobs.pop(project_id)

    async def get_scheduled_projects(
        self, organization_id: str | None = None
    ) -> list[ProjectScheduleResponse]:
        return list(self._jobs.values())


@pytest.fixture
async def project_scheduler_client():
    scheduler_manager = _FakeProjectSchedulerManager()
    app.dependency_overrides[get_project_scheduler_manager] = lambda: scheduler_manager

    client = AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test-project-scheduler",
    )
    try:
        yield client
    finally:
        await client.aclose()
        app.dependency_overrides.pop(get_project_scheduler_manager, None)


async def test_schedule_project_and_read_scheduled(project_scheduler_client: AsyncClient) -> None:
    project_id = str(uuid4())
    cron = "*/5 * * * *"

    schedule_response = await project_scheduler_client.post(
        "/projects/schedule",
        json={
            "project_id": project_id,
            "cron": cron,
            "scheduled_by_user_id": str(uuid4()),
            "mode": PipelineExecutionMode.FULL.value,
            "force_exec": True,
            "max_retries": 3,
            "retry_delay_seconds": 30,
            "retry_backoff": RetryBackoff.EXPONENTIAL.value,
            "retry_max_delay_seconds": 300,
        },
    )
    assert schedule_response.status_code == 200
    schedule_payload = schedule_response.json()
    assert schedule_payload["success"] is True
    assert schedule_payload["project_id"] == project_id
    assert schedule_payload["message"] == f"Project scheduled with cron '{cron}'"

    list_response = await project_scheduler_client.get("/projects/scheduled/")
    assert list_response.status_code == 200
    list_payload = list_response.json()
    assert len(list_payload) == 1
    assert list_payload[0]["project_id"] == project_id
    assert list_payload[0]["task_id"] == project_id
    assert list_payload[0]["mode"] == PipelineExecutionMode.FULL.value
    assert list_payload[0]["force_exec"] is True
    assert list_payload[0]["max_retries"] == 3
    assert list_payload[0]["retry_delay_seconds"] == 30
    assert list_payload[0]["retry_backoff"] == RetryBackoff.EXPONENTIAL.value
    assert list_payload[0]["retry_max_delay_seconds"] == 300


async def test_unschedule_project_removes_job(project_scheduler_client: AsyncClient) -> None:
    project_id = str(uuid4())

    schedule_response = await project_scheduler_client.post(
        "/projects/schedule",
        json={
            "project_id": project_id,
            "cron": "0 * * * *",
            "scheduled_by_user_id": str(uuid4()),
        },
    )
    assert schedule_response.status_code == 200

    unschedule_response = await project_scheduler_client.post(f"/projects/unschedule/{project_id}")
    assert unschedule_response.status_code == 200
    unschedule_payload = unschedule_response.json()
    assert unschedule_payload["success"] is True
    assert unschedule_payload["project_id"] == project_id
    assert unschedule_payload["message"] == "Project unscheduled"

    list_response = await project_scheduler_client.get("/projects/scheduled/")
    assert list_response.status_code == 200
    payload = list_response.json()
    assert len(payload) == 1
    assert payload[0]["project_id"] == project_id
    assert payload[0]["disabled"] is True
    assert payload[0]["task_id"] is None


async def test_update_schedule_project_updates_existing_job(
    project_scheduler_client: AsyncClient,
) -> None:
    project_id = str(uuid4())

    create_response = await project_scheduler_client.post(
        "/projects/schedule",
        json={
            "project_id": project_id,
            "cron": "*/10 * * * *",
            "scheduled_by_user_id": str(uuid4()),
        },
    )
    assert create_response.status_code == 200

    updated_by_user_id = str(uuid4())
    update_response = await project_scheduler_client.patch(
        f"/projects/schedule/{project_id}",
        json={
            "cron": "15 * * * *",
            "scheduled_by_user_id": updated_by_user_id,
            "mode": PipelineExecutionMode.METADATA_ONLY.value,
            "force_exec": True,
            "max_retries": 2,
            "retry_delay_seconds": 15,
            "retry_backoff": RetryBackoff.EXPONENTIAL.value,
            "retry_max_delay_seconds": 120,
        },
    )
    assert update_response.status_code == 200
    update_payload = update_response.json()
    assert update_payload["success"] is True
    assert update_payload["project_id"] == project_id
    assert update_payload["message"] == "Project schedule updated"

    list_response = await project_scheduler_client.get("/projects/scheduled/")
    assert list_response.status_code == 200
    payload = list_response.json()
    assert len(payload) == 1
    assert payload[0]["project_id"] == project_id
    assert payload[0]["cron"] == "15 * * * *"
    assert payload[0]["scheduled_by_user_id"] == updated_by_user_id
    assert payload[0]["mode"] == PipelineExecutionMode.METADATA_ONLY.value
    assert payload[0]["force_exec"] is True
    assert payload[0]["max_retries"] == 2
    assert payload[0]["retry_delay_seconds"] == 15
    assert payload[0]["retry_backoff"] == RetryBackoff.EXPONENTIAL.value
    assert payload[0]["retry_max_delay_seconds"] == 120
    assert payload[0]["task_id"] == project_id


async def test_schedule_project_ignores_extra_next_run_time_input(
    project_scheduler_client: AsyncClient,
) -> None:
    project_id = str(uuid4())

    response = await project_scheduler_client.post(
        "/projects/schedule",
        json={
            "project_id": project_id,
            "cron": "0 5 * * MON",
            "scheduled_by_user_id": str(uuid4()),
            "next_run_time": datetime.now(tz=UTC).replace(microsecond=0).isoformat(),
        },
    )

    assert response.status_code == 200

    list_response = await project_scheduler_client.get("/projects/scheduled/")
    assert list_response.status_code == 200
    payload = list_response.json()
    assert len(payload) == 1
    assert payload[0]["project_id"] == project_id
    assert payload[0]["next_run_time"] is None


async def test_patch_schedule_project_can_change_disabled(
    project_scheduler_client: AsyncClient,
) -> None:
    project_id = str(uuid4())

    schedule_response = await project_scheduler_client.post(
        "/projects/schedule",
        json={
            "project_id": project_id,
            "cron": "0 * * * *",
            "scheduled_by_user_id": str(uuid4()),
        },
    )
    assert schedule_response.status_code == 200

    disable_response = await project_scheduler_client.patch(
        f"/projects/schedule/{project_id}",
        json={"disabled": True},
    )
    assert disable_response.status_code == 200

    list_response = await project_scheduler_client.get("/projects/scheduled/")
    assert list_response.status_code == 200
    payload = list_response.json()
    assert len(payload) == 1
    assert payload[0]["project_id"] == project_id
    assert payload[0]["disabled"] is True
    assert payload[0]["task_id"] is None

    enable_response = await project_scheduler_client.patch(
        f"/projects/schedule/{project_id}",
        json={"disabled": False, "mode": PipelineExecutionMode.METADATA_ONLY.value, "force_exec": True},
    )
    assert enable_response.status_code == 200

    list_response = await project_scheduler_client.get("/projects/scheduled/")
    assert list_response.status_code == 200
    payload = list_response.json()
    assert len(payload) == 1
    assert payload[0]["project_id"] == project_id
    assert payload[0]["disabled"] is False
    assert payload[0]["task_id"] == project_id
    assert payload[0]["mode"] == PipelineExecutionMode.METADATA_ONLY.value
    assert payload[0]["force_exec"] is True


async def test_delete_schedule_project_removes_schedule(
    project_scheduler_client: AsyncClient,
) -> None:
    project_id = str(uuid4())

    schedule_response = await project_scheduler_client.post(
        "/projects/schedule",
        json={
            "project_id": project_id,
            "cron": "0 * * * *",
            "scheduled_by_user_id": str(uuid4()),
        },
    )
    assert schedule_response.status_code == 200

    delete_response = await project_scheduler_client.delete(f"/projects/schedule/{project_id}")
    assert delete_response.status_code == 200
    delete_payload = delete_response.json()
    assert delete_payload["success"] is True
    assert delete_payload["project_id"] == project_id
    assert delete_payload["message"] == "Project schedule deleted"

    list_response = await project_scheduler_client.get("/projects/scheduled/")
    assert list_response.status_code == 200
    assert list_response.json() == []


async def test_schedule_project_requires_cron(project_scheduler_client: AsyncClient) -> None:
    response = await project_scheduler_client.post(
        "/projects/schedule",
        json={
            "project_id": str(uuid4()),
        },
    )
    assert response.status_code == 422


async def test_reschedule_same_project_replaces_existing_job(
    project_scheduler_client: AsyncClient,
) -> None:
    project_id = str(uuid4())

    first_response = await project_scheduler_client.post(
        "/projects/schedule",
        json={
            "project_id": project_id,
            "cron": "*/10 * * * *",
            "scheduled_by_user_id": str(uuid4()),
        },
    )
    assert first_response.status_code == 200

    second_response = await project_scheduler_client.post(
        "/projects/schedule",
        json={
            "project_id": project_id,
            "cron": "15 * * * *",
            "scheduled_by_user_id": str(uuid4()),
            "mode": PipelineExecutionMode.METADATA_ONLY.value,
        },
    )
    assert second_response.status_code == 200

    list_response = await project_scheduler_client.get("/projects/scheduled/")
    assert list_response.status_code == 200
    payload = list_response.json()
    assert len(payload) == 1
    assert payload[0]["project_id"] == project_id
    assert payload[0]["task_id"] == project_id
    assert payload[0]["cron"] == "15 * * * *"
    assert payload[0]["mode"] == PipelineExecutionMode.METADATA_ONLY.value


async def test_unschedule_unknown_project_is_idempotent(
    project_scheduler_client: AsyncClient,
) -> None:
    unknown_project_id = str(uuid4())

    response = await project_scheduler_client.post(f"/projects/unschedule/{unknown_project_id}")
    assert response.status_code == 200

    payload = response.json()
    assert payload["success"] is True
    assert payload["project_id"] == unknown_project_id
    assert payload["message"] == "Project unscheduled"


async def test_schedule_project_uses_default_mode_and_force_exec(
    project_scheduler_client: AsyncClient,
) -> None:
    project_id = str(uuid4())

    schedule_response = await project_scheduler_client.post(
        "/projects/schedule",
        json={
            "project_id": project_id,
            "cron": "30 2 * * *",
            "scheduled_by_user_id": str(uuid4()),
        },
    )
    assert schedule_response.status_code == 200

    list_response = await project_scheduler_client.get("/projects/scheduled/")
    assert list_response.status_code == 200
    payload = list_response.json()
    assert len(payload) == 1
    assert payload[0]["project_id"] == project_id
    assert payload[0]["mode"] == PipelineExecutionMode.FULL.value
    assert payload[0]["force_exec"] is False
