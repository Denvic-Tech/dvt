from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from src.enums import RetryBackoff
from src.managers import project_scheduler as project_scheduler_module
from src.managers.project_scheduler import ProjectSchedulerManager
from src.modules.project.domain import ProjectScheduleRunStatus
from src.modules.project.infra.db_models import ProjectScheduleRunRecord
from src.modules.task_execution.domain.types import TaskExecutionStatus, TaskTerminationReason
from src.pipeline.execution_mode import PipelineExecutionMode
from src.schemas.internal.project_scheduler import (
    ProjectSchedulePatchRequest,
    ProjectScheduleRequest,
)


class _FakeScalarResult:
    def __init__(self, first_value):
        self._first = first_value

    def first(self):
        return self._first


class _FakeAsyncSession:
    def __init__(self) -> None:
        self.committed = False

    async def commit(self) -> None:
        self.committed = True


class _FakeAsyncSessionFactory:
    def __init__(self) -> None:
        self.session = _FakeAsyncSession()

    def __call__(self, _engine):
        return self

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_patch_schedule_recomputes_next_run_time_when_cron_changes(monkeypatch):
    manager = ProjectSchedulerManager()
    schedule = SimpleNamespace(
        project_id="project-1",
        cron="0 * * * *",
        disabled=False,
        scheduled_by_user_id="user-1",
        mode=PipelineExecutionMode.FULL,
        force_exec=False,
        max_retries=0,
        retry_delay_seconds=60,
        retry_backoff=RetryBackoff.FIXED,
        retry_max_delay_seconds=3600,
    )
    old_next_run_time = datetime(2026, 4, 7, 10, 0, tzinfo=UTC)
    fake_session_factory = _FakeAsyncSessionFactory()
    scheduled_calls = []

    async def fake_get_project_schedules_by(*_args, **_kwargs):
        return _FakeScalarResult(schedule)

    async def fake_update_project_schedule(*_args, **_kwargs):
        return schedule

    monkeypatch.setattr(project_scheduler_module, "AsyncSession", fake_session_factory)
    monkeypatch.setattr(
        project_scheduler_module.project_schedule_crud,
        "get_project_schedules_by",
        fake_get_project_schedules_by,
    )
    monkeypatch.setattr(
        project_scheduler_module.project_schedule_crud,
        "update_project_schedule",
        fake_update_project_schedule,
    )
    monkeypatch.setattr(
        manager,
        "get_job",
        lambda _project_id: SimpleNamespace(
            next_run_time=old_next_run_time,
            kwargs={"mode": PipelineExecutionMode.FULL, "force_exec": False},
        ),
    )
    monkeypatch.setattr(
        manager,
        "_schedule_project_in_memory",
        lambda **kwargs: scheduled_calls.append(kwargs),
    )

    await manager.patch_project_schedule(
        project_id="project-1",
        patch=ProjectSchedulePatchRequest(cron="15 * * * *"),
    )

    assert fake_session_factory.session.committed is True
    assert scheduled_calls == [
        {
            "project_id": "project-1",
            "cron": "15 * * * *",
            "next_run_time": None,
        }
    ]


@pytest.mark.asyncio
async def test_patch_schedule_keeps_current_next_run_time_when_cron_is_unchanged(monkeypatch):
    manager = ProjectSchedulerManager()
    schedule = SimpleNamespace(
        project_id="project-1",
        cron="0 * * * *",
        disabled=False,
        scheduled_by_user_id="user-1",
        mode=PipelineExecutionMode.FULL,
        force_exec=False,
        max_retries=0,
        retry_delay_seconds=60,
        retry_backoff=RetryBackoff.FIXED,
        retry_max_delay_seconds=3600,
    )
    current_next_run_time = datetime(2026, 4, 7, 10, 0, tzinfo=UTC)
    fake_session_factory = _FakeAsyncSessionFactory()
    scheduled_calls = []

    async def fake_get_project_schedules_by(*_args, **_kwargs):
        return _FakeScalarResult(schedule)

    async def fake_update_project_schedule(*_args, **_kwargs):
        return schedule

    monkeypatch.setattr(project_scheduler_module, "AsyncSession", fake_session_factory)
    monkeypatch.setattr(
        project_scheduler_module.project_schedule_crud,
        "get_project_schedules_by",
        fake_get_project_schedules_by,
    )
    monkeypatch.setattr(
        project_scheduler_module.project_schedule_crud,
        "update_project_schedule",
        fake_update_project_schedule,
    )
    monkeypatch.setattr(
        manager,
        "get_job",
        lambda _project_id: SimpleNamespace(
            next_run_time=current_next_run_time,
            kwargs={"mode": PipelineExecutionMode.FULL, "force_exec": False},
        ),
    )
    monkeypatch.setattr(
        manager,
        "_schedule_project_in_memory",
        lambda **kwargs: scheduled_calls.append(kwargs),
    )

    await manager.patch_project_schedule(
        project_id="project-1",
        patch=ProjectSchedulePatchRequest(
            mode=PipelineExecutionMode.METADATA_ONLY,
            force_exec=True,
        ),
    )

    assert fake_session_factory.session.committed is True
    assert scheduled_calls == [
        {
            "project_id": "project-1",
            "cron": "0 * * * *",
            "next_run_time": current_next_run_time,
        }
    ]


def _make_run(**overrides) -> ProjectScheduleRunRecord:
    values = {
        "schedule_id": "schedule-1",
        "scheduled_at": datetime(2026, 8, 10, tzinfo=UTC),
        "max_retries": 3,
        "retry_delay_seconds": 10,
        "retry_backoff": RetryBackoff.FIXED,
        "retry_max_delay_seconds": 25,
        "mode": PipelineExecutionMode.FULL,
        "force_exec": False,
        "attempt_number": 1,
    }
    values.update(overrides)
    return ProjectScheduleRunRecord(**values)


def test_retry_delay_supports_fixed_and_capped_exponential_backoff():
    manager = ProjectSchedulerManager()
    fixed_run = _make_run(retry_backoff=RetryBackoff.FIXED)
    exponential_run = _make_run(retry_backoff=RetryBackoff.EXPONENTIAL)

    assert manager.calculate_retry_delay_seconds(fixed_run, 3) == 10
    assert manager.calculate_retry_delay_seconds(exponential_run, 1) == 10
    assert manager.calculate_retry_delay_seconds(exponential_run, 2) == 20
    assert manager.calculate_retry_delay_seconds(exponential_run, 3) == 25


def test_failed_attempt_waits_for_retry_until_limit_is_exhausted():
    manager = ProjectSchedulerManager()
    now = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
    run = _make_run(max_retries=1, attempt_number=1)

    manager._record_attempt_failure(run, now=now, error="first failure")

    assert run.status == ProjectScheduleRunStatus.WAITING_RETRY
    assert run.next_retry_at == now.replace(second=10)
    assert run.finished_at is None

    run.attempt_number = 2
    manager._record_attempt_failure(run, now=now, error="second failure")

    assert run.status == ProjectScheduleRunStatus.ERROR
    assert run.next_retry_at is None
    assert run.finished_at == now
    assert run.last_error == "second failure"


def test_worker_lost_error_uses_scheduler_retry_policy():
    manager = ProjectSchedulerManager()
    now = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
    run = _make_run(max_retries=2, attempt_number=1)
    task = SimpleNamespace(
        status=TaskExecutionStatus.ERROR,
        message=None,
        termination_reason=TaskTerminationReason.WORKER_LOST,
    )

    assert manager._apply_task_result(run, task=task, now=now) is True
    assert run.status == ProjectScheduleRunStatus.WAITING_RETRY
    assert run.next_retry_at == now.replace(second=10)
    assert run.last_error == TaskTerminationReason.WORKER_LOST


def test_superseded_scheduled_execution_finishes_without_retry():
    manager = ProjectSchedulerManager()
    now = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
    run = _make_run(max_retries=3, attempt_number=1)
    task = SimpleNamespace(
        status=TaskExecutionStatus.CANCELLED,
        message=None,
        termination_reason=TaskTerminationReason.SUPERSEDED_BY_NEWER_EXECUTION,
    )

    assert manager._apply_task_result(run, task=task, now=now) is True
    assert run.status == ProjectScheduleRunStatus.CANCELLED
    assert run.next_retry_at is None
    assert run.finished_at == now
    assert run.last_error == TaskTerminationReason.SUPERSEDED_BY_NEWER_EXECUTION


def test_schedule_request_validates_retry_limits_and_exponential_cap():
    with pytest.raises(ValidationError):
        ProjectScheduleRequest(project_id="project-1", cron="0 * * * *", max_retries=11)

    with pytest.raises(ValidationError, match="retry_max_delay_seconds"):
        ProjectScheduleRequest(
            project_id="project-1",
            cron="0 * * * *",
            retry_backoff=RetryBackoff.EXPONENTIAL,
            retry_delay_seconds=120,
            retry_max_delay_seconds=60,
        )


def test_schedule_response_exposes_persisted_policy_and_latest_chain(monkeypatch):
    manager = ProjectSchedulerManager()
    monkeypatch.setattr(manager, "get_job", lambda _project_id: None)
    schedule = SimpleNamespace(
        id="schedule-1",
        project_id="project-1",
        cron="0 * * * *",
        disabled=False,
        scheduled_by_user_id="user-1",
        mode=PipelineExecutionMode.FULL,
        force_exec=True,
        max_retries=3,
        retry_delay_seconds=10,
        retry_backoff=RetryBackoff.EXPONENTIAL,
        retry_max_delay_seconds=60,
    )
    run = _make_run(
        id="run-1",
        status=ProjectScheduleRunStatus.WAITING_RETRY,
        attempt_number=2,
        max_retries=3,
        current_task_id="task-2",
        next_retry_at=datetime(2026, 8, 10, 12, 1, tzinfo=UTC),
        last_error="temporary error",
    )

    response = manager._to_schedule_response(schedule, run)

    assert response.max_retries == 3
    assert response.retry_backoff == RetryBackoff.EXPONENTIAL
    assert response.latest_run_chain is not None
    assert response.latest_run_chain.run_id == "run-1"
    assert response.latest_run_chain.attempt_number == 2
    assert response.latest_run_chain.max_attempts == 4
