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

    other_user = UserRecord(
        email=f"retained-{suffix}@example.com",
        hashed_password="hashed",
        auth_provider="email",
        is_verified=True,
        is_active=True,
        role=DVTDefaultRoles.ADMIN.value,
        organization_id=organization.id,
    )
    test_db_async_session.add(other_user)
    await test_db_async_session.flush()
    other_folder = ProjectFolderRecord(
        name="Retained folder",
        user_id=other_user.id,
        organization_id=organization.id,
    )
    test_db_async_session.add(other_folder)
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

    node = GraphNodeRecord(
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
    test_db_async_session.add(node)
    await test_db_async_session.flush()

    analysis = AIAnalysisRequestRecord(
        task_id=task.task_id,
        project_id=project.id,
        user_id=user.id,
        organization_id=organization.id,
    )
    test_db_async_session.add(analysis)
    await test_db_async_session.flush()

    file_object = DVTServiceFileObjectRecord(
        organization_id=organization.id,
        project_id=project.id,
        parent_path="",
        name="input.csv",
        is_dir=False,
    )
    test_db_async_session.add(file_object)
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
    deleted_records = (
        (ProjectFolderRecord.id, folder.id),
        (ProjectRecord.id, project.id),
        (ProjectScheduleRecord.id, schedule.id),
        (ProjectScheduleRunRecord.id, run.id),
        (TaskRecord.task_id, task.task_id),
        (GraphNodeRecord.id, node.id),
        (AIAnalysisRequestRecord.id, analysis.id),
        (DVTServiceFileObjectRecord.id, file_object.id),
    )
    await delete_users(test_db_async_session, [user], soft_delete=False)
    await test_db_async_session.commit()

    assert await test_db_async_session.get(UserRecord, user.id) is None
    for id_column, record_id in deleted_records:
        remaining_id = await test_db_async_session.scalar(
            sa.select(id_column).where(id_column == record_id)
        )
        assert remaining_id is None

    assert await test_db_async_session.scalar(
        sa.select(UserRecord.id).where(UserRecord.id == other_user.id)
    ) == other_user.id
    assert await test_db_async_session.scalar(
        sa.select(ProjectFolderRecord.id).where(ProjectFolderRecord.id == other_folder.id)
    ) == other_folder.id

    persisted_log = await test_db_async_session.get(LogRecord, log.id)
    assert persisted_log is not None
    assert persisted_log.user_id is None
    assert persisted_log.task_id is None
