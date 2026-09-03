from __future__ import annotations

import sqlalchemy as sa

from src.modules.task_execution.domain.types import TaskExecutionStatus, TaskSource
from src.modules.task_execution.infra.db_models import TaskRecord
from src.pipeline.execution_mode import PipelineExecutionMode


def test_task_source_persists_uppercase_and_roundtrips_through_orm(
    test_db_session,
    test_admin_user,
    test_admin_project,
) -> None:
    task = TaskRecord(
        task_id="task-source-roundtrip",
        user_id=test_admin_user.id,
        organization_id=test_admin_user.organization_id,
        project_id=test_admin_project.id,
        mode=PipelineExecutionMode.FULL,
        status=TaskExecutionStatus.PENDING,
        source=TaskSource.API,
    )

    test_db_session.add(task)
    test_db_session.commit()
    test_db_session.expire_all()

    stored_source = test_db_session.execute(
        sa.text("SELECT source FROM tasks WHERE task_id = :task_id"),
        {"task_id": task.task_id},
    ).scalar_one()
    loaded_task = test_db_session.get(TaskRecord, task.task_id)

    assert stored_source == TaskSource.API.value
    assert loaded_task is not None
    assert loaded_task.source == TaskSource.API.value
