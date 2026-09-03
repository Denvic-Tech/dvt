from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.enums import (
    DVTDefaultRoles,
    RetryBackoff,
)
from src.managers import project_scheduler as project_scheduler_module
from src.managers.project_scheduler import ProjectSchedulerManager
from src.models import OrganizationRecord
from src.modules.project.domain import ProjectScheduleRunStatus
from src.modules.project.infra.db_models import (
    ProjectRecord,
    ProjectScheduleRecord,
    ProjectScheduleRunRecord,
)
from src.modules.task_execution.domain.types import TaskExecutionStatus
from src.modules.task_execution.infra.db_models import TaskRecord
from src.modules.user.infra.db_models import UserRecord

pytestmark = pytest.mark.asyncio


async def test_reconciler_retries_failed_task_and_finishes_on_success(
    test_db_async_engine,
    monkeypatch,
) -> None:
    session_factory = async_sessionmaker(test_db_async_engine, expire_on_commit=False)
    suffix = uuid4().hex
    async with session_factory() as session:
        organization = OrganizationRecord(name=f"Manager retry org {suffix}")
        session.add(organization)
        await session.flush()
        user = UserRecord(
            email=f"manager-retry-{suffix}@example.com",
            hashed_password="hashed",
            auth_provider="email",
            is_verified=True,
            is_active=True,
            role=DVTDefaultRoles.ADMIN.value,
            organization_id=organization.id,
        )
        session.add(user)
        await session.flush()
        project = ProjectRecord(
            name="Manager retry project",
            user_id=user.id,
            organization_id=organization.id,
        )
        session.add(project)
        await session.flush()
        schedule = ProjectScheduleRecord(
            project_id=project.id,
            scheduled_by_user_id=user.id,
            cron="0 * * * *",
            max_retries=1,
            retry_delay_seconds=1,
            retry_backoff=RetryBackoff.FIXED,
            retry_max_delay_seconds=60,
        )
        session.add(schedule)
        await session.commit()

    enqueue_calls: list[tuple[str, int]] = []

    async def fake_enqueue_task_from_project(
        *,
        project,
        mode,
        force_exec,
        user,
        session,
        source,
        schedule_run_id,
        schedule_attempt,
        **_kwargs,
    ):
        task_id = f"{schedule_run_id}-attempt-{schedule_attempt}"
        task = TaskRecord(
            task_id=task_id,
            mode=mode,
            force_exec=force_exec,
            status=TaskExecutionStatus.PENDING,
            source=source.value,
            user_id=user.id,
            organization_id=project.organization_id,
            project_id=project.id,
            schedule_run_id=schedule_run_id,
            schedule_attempt=schedule_attempt,
        )
        session.add(task)
        await session.commit()
        enqueue_calls.append((schedule_run_id, schedule_attempt))
        return SimpleNamespace(task_id=task_id)

    monkeypatch.setattr(project_scheduler_module, "engine", test_db_async_engine)
    monkeypatch.setattr(
        project_scheduler_module,
        "enqueue_task_from_project",
        fake_enqueue_task_from_project,
    )
    manager = ProjectSchedulerManager()

    await manager.start_scheduled_run(project.id)
    await manager.start_scheduled_run(project.id)
    await manager.reconcile_once()

    async with session_factory() as session:
        runs = list(
            (
                await session.execute(
                    sa.select(ProjectScheduleRunRecord).where(
                        ProjectScheduleRunRecord.schedule_id == schedule.id
                    )
                )
            ).scalars()
        )
        assert len(runs) == 1
        first_task = (
            (
                await session.execute(
                    sa.select(TaskRecord).where(TaskRecord.schedule_run_id == runs[0].id)
                )
            )
            .scalars()
            .one()
        )
        first_task.status = TaskExecutionStatus.ERROR
        first_task.message = "temporary failure"
        first_task.finished_at = datetime.now(tz=UTC)
        session.add(first_task)
        await session.commit()

    await manager.reconcile_once()
    async with session_factory() as session:
        run = (
            (
                await session.execute(
                    sa.select(ProjectScheduleRunRecord).where(
                        ProjectScheduleRunRecord.schedule_id == schedule.id
                    )
                )
            )
            .scalars()
            .one()
        )
        assert run.status == ProjectScheduleRunStatus.WAITING_RETRY
        run.next_retry_at = datetime.now(tz=UTC) - timedelta(seconds=1)
        session.add(run)
        await session.commit()

    await manager.reconcile_once()
    async with session_factory() as session:
        tasks = list(
            (
                await session.execute(
                    sa.select(TaskRecord)
                    .where(TaskRecord.schedule_run_id == run.id)
                    .order_by(TaskRecord.schedule_attempt)
                )
            ).scalars()
        )
        assert [task.schedule_attempt for task in tasks] == [1, 2]
        tasks[1].status = TaskExecutionStatus.SUCCESS
        tasks[1].finished_at = datetime.now(tz=UTC)
        session.add(tasks[1])
        await session.commit()

    await manager.reconcile_once()
    async with session_factory() as session:
        finished_run = await session.get(ProjectScheduleRunRecord, run.id)
        assert finished_run.status == ProjectScheduleRunStatus.SUCCESS
        assert finished_run.finished_at is not None

    assert [attempt for _run_id, attempt in enqueue_calls] == [1, 2]
