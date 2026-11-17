from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import pytest

from src.enums import DVTDefaultRoles
from src.modules.project.infra.db_models import ProjectRecord
from src.modules.task_execution.domain.types import TaskExecutionStatus, TaskSource
from src.modules.task_execution.infra.db_models import TaskRecord
from src.modules.user.infra.db_models import UserRecord
from src.pipeline.execution_mode import PipelineExecutionMode


@pytest.fixture
def create_user(db_session):
    def _create(*, organization_id: str, role: str = DVTDefaultRoles.USER.value) -> UserRecord:
        user = UserRecord(
            email=f"user-{uuid4()}@example.com",
            hashed_password="hashed",
            auth_provider="email",
            is_verified=True,
            is_active=True,
            role=role,
            organization_id=organization_id,
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)
        return user

    return _create


@pytest.fixture
def create_project(db_session):
    def _create(*, user: UserRecord, name: str = "Widget project", is_deleted: bool = False) -> ProjectRecord:
        project = ProjectRecord(
            id=str(uuid4()),
            name=name,
            user_id=user.id,
            organization_id=user.organization_id,
            is_deleted=is_deleted,
        )
        db_session.add(project)
        db_session.commit()
        db_session.refresh(project)
        return project

    return _create


@pytest.fixture
def add_task(db_session):
    def _add(
            *,
            user: UserRecord,
            project: ProjectRecord,
            queued_at: datetime,
            status: TaskExecutionStatus = TaskExecutionStatus.SUCCESS,
            source: TaskSource = TaskSource.UI,
            mode: PipelineExecutionMode = PipelineExecutionMode.FULL,
            termination_reason: str | None = None,
            started_at: datetime | None = None,
            finished_at: datetime | None = None,
    ) -> TaskRecord:
        task = TaskRecord(
            task_id=str(uuid4()),
            mode=mode,
            status=status,
            source=source,
            queued_at=queued_at,
            started_at=started_at,
            finished_at=finished_at,
            termination_reason=termination_reason,
            user_id=user.id,
            organization_id=user.organization_id,
            project_id=project.id,
        )
        db_session.add(task)
        db_session.commit()
        return task

    return _add


@pytest.fixture
def set_current_user(gateway_client):
    """Подменить текущего пользователя для обычных и admin-only виджетов."""
    from services.gateway.main import app
    from services.gateway.routes.widgets.impl import get_widgets_admin_user

    from src.modules.user.infra.fastapi.dependencies import get_user_access_only

    dependencies = [get_user_access_only, get_widgets_admin_user]
    previous = {dependency: app.dependency_overrides.get(dependency) for dependency in dependencies}

    def _set(user: UserRecord) -> None:
        for dependency in dependencies:
            app.dependency_overrides[dependency] = lambda user=user: user

    yield _set

    for dependency, override in previous.items():
        if override is None:
            app.dependency_overrides.pop(dependency, None)
        else:
            app.dependency_overrides[dependency] = override
