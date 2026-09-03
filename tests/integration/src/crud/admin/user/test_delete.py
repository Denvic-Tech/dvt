from datetime import UTC, datetime
from uuid import uuid4

import pytest
import sqlalchemy as sa

from src.crud.admin.user.delete import delete_users
from src.enums import DVTDefaultRoles
from src.models import (
    AIAnalysisRequestRecord,
    LogRecord,
    OrganizationRecord,
)
from src.modules.file_storage.infra.db_models import DVTServiceFileObjectRecord
from src.modules.pipeline_graph.infra.db_models import GraphNodeRecord
from src.modules.project.infra.db_models import (
    ProjectFolderRecord,
    ProjectRecord,
    ProjectScheduleRecord,
    ProjectScheduleRunRecord,
)
from src.modules.task_execution.domain.types import TaskExecutionStatus
from src.modules.task_execution.infra.db_models import TaskRecord
from src.modules.user.infra.db_models import UserRecord
from src.pipeline.execution_mode import PipelineExecutionMode

pytestmark = pytest.mark.asyncio


async def test_hard_delete_user_cleans_project_dependencies_without_relationships(
    test_db_async_session,
) -> None:
    suffix = uuid4().hex
    organization = OrganizationRecord(name=f"Hard delete org {suffix}")
    test_db_async_session.add(organization)
    await test_db_async_session.flush()

    user = UserRecord(
        email=f"hard-delete-{suffix}@example.com",
        hashed_password="hashed",
        auth_provider="email",
        is_verified=True,
        is_active=True,
        role=DVTDefaultRoles.ADMIN.value,
        organization_id=organization.id,
    )
    test_db_async_session.add(user)
    await test_db_async_session.flush()

    folder = ProjectFolderRecord(
        name="Hard delete folder",
        user_id=user.id,
        organization_id=organization.id,
    )
    test_db_async_session.add(folder)
    await test_db_async_session.flush()

    project = ProjectRecord(
        name="Hard delete project",
        user_id=user.id,
        organization_id=organization.id,
        folder_id=folder.id,
    )
    test_db_async_session.add(project)
    await test_db_async_session.flush()

    schedule = ProjectScheduleRecord(
        project_id=project.id,
        scheduled_by_user_id=user.id,
        cron="0 * * * *",
    )
    test_db_async_session.add(schedule)
    await test_db_async_session.flush()

    run = ProjectScheduleRunRecord(
        schedule_id=schedule.id,
        scheduled_at=datetime.now(tz=UTC),
    )
    test_db_async_session.add(run)
    await test_db_async_session.flush()

    task = TaskRecord(
        task_id=f"hard-delete-task-{suffix}",
        mode=PipelineExecutionMode.FULL,
        status=TaskExecutionStatus.SUCCESS,
        user_id=user.id,
        organization_id=organization.id,
        project_id=project.id,
        schedule_run_id=run.id,
        schedule_attempt=1,
    )
    test_db_async_session.add(task)
    await test_db_async_session.flush()

    test_db_async_session.add(
        GraphNodeRecord(
            ui_id=f"node-{suffix}",
            type="input",
            position_x=0.0,
            position_y=0.0,
            selected=False,
            name="Hard delete node",
            display_name="Hard delete node",
            input_values={},
            project_id=project.id,
            organization_id=organization.id,
            user_id=user.id,
        )
    )
    await test_db_async_session.flush()

    test_db_async_session.add(
        AIAnalysisRequestRecord(
            task_id=task.task_id,
            project_id=project.id,
            user_id=user.id,
            organization_id=organization.id,
        )
    )
    await test_db_async_session.flush()

    test_db_async_session.add(
        DVTServiceFileObjectRecord(
            organization_id=organization.id,
            project_id=project.id,
            parent_path="",
            name="input.csv",
            is_dir=False,
        )
    )
    await test_db_async_session.flush()

    test_db_async_session.add(
        LogRecord(
            level="INFO",
            service_name="test",
            message="linked log",
            user_id=user.id,
            task_id=task.task_id,
        )
    )
    await test_db_async_session.flush()

    await test_db_async_session.commit()

    log = (
        await test_db_async_session.execute(
            sa.select(LogRecord).where(LogRecord.task_id == task.task_id)
        )
    ).scalar_one()
    await delete_users(test_db_async_session, [user], soft_delete=False)
    await test_db_async_session.commit()

    assert await test_db_async_session.get(UserRecord, user.id) is None
    for model in (
        ProjectFolderRecord,
        ProjectRecord,
        ProjectScheduleRecord,
        ProjectScheduleRunRecord,
        TaskRecord,
        GraphNodeRecord,
        AIAnalysisRequestRecord,
        DVTServiceFileObjectRecord,
    ):
        assert (await test_db_async_session.execute(sa.select(model))).scalars().all() == []

    persisted_log = await test_db_async_session.get(LogRecord, log.id)
    assert persisted_log is not None
    assert persisted_log.user_id is None
    assert persisted_log.task_id is None
