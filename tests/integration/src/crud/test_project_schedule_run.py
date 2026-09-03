from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from src.crud import (
    project_schedule as project_schedule_crud,
    project_schedule_run as schedule_run_crud,
)
from src.enums import DVTDefaultRoles
from src.models import OrganizationRecord
from src.modules.project.infra.db_models import ProjectRecord
from src.modules.task_execution.domain.types import TaskExecutionStatus
from src.modules.task_execution.infra.db_models import TaskRecord
from src.modules.user.infra.db_models import UserRecord
from src.pipeline.execution_mode import PipelineExecutionMode

pytestmark = pytest.mark.asyncio


async def test_schedule_run_links_attempt_and_rejects_overlapping_chain(
    test_db_async_session,
) -> None:
    suffix = uuid4().hex
    organization = OrganizationRecord(name=f"Retry org {suffix}")
    test_db_async_session.add(organization)
    await test_db_async_session.flush()
    user = UserRecord(
        email=f"retry-{suffix}@example.com",
        hashed_password="hashed",
        auth_provider="email",
        is_verified=True,
        is_active=True,
        role=DVTDefaultRoles.ADMIN.value,
        organization_id=organization.id,
    )
    test_db_async_session.add(user)
    await test_db_async_session.flush()
    project = ProjectRecord(
        name="Retry project",
        user_id=user.id,
        organization_id=organization.id,
    )
    test_db_async_session.add(project)
    await test_db_async_session.flush()
    schedule = await project_schedule_crud.create_project_schedule(
        test_db_async_session,
        project_id=project.id,
        cron="0 * * * *",
        scheduled_by_user_id=user.id,
        max_retries=2,
    )
    run = await schedule_run_crud.create_project_schedule_run(
        test_db_async_session,
        schedule=schedule,
        scheduled_at=datetime.now(tz=UTC),
    )
    await test_db_async_session.commit()

    task = TaskRecord(
        task_id=f"task-{suffix}",
        mode=PipelineExecutionMode.FULL,
        status=TaskExecutionStatus.ERROR,
        user_id=user.id,
        organization_id=organization.id,
        project_id=project.id,
        schedule_run_id=run.id,
        schedule_attempt=1,
    )
    test_db_async_session.add(task)
    await test_db_async_session.commit()

    attempt = await schedule_run_crud.get_attempt_task(
        test_db_async_session,
        run_id=run.id,
        attempt_number=1,
    )
    latest = await schedule_run_crud.get_latest_runs_by_schedule_ids(
        test_db_async_session,
        schedule_ids=[schedule.id],
    )
    assert attempt is not None and attempt.task_id == task.task_id
    assert latest[schedule.id].id == run.id

    with pytest.raises(IntegrityError):
        await schedule_run_crud.create_project_schedule_run(
            test_db_async_session,
            schedule=schedule,
            scheduled_at=datetime.now(tz=UTC),
        )
    await test_db_async_session.rollback()
