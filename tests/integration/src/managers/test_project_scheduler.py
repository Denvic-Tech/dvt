from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.enums import DVTDefaultRoles
from src.managers import project_scheduler as project_scheduler_module
from src.managers.project_scheduler import ProjectSchedulerManager
from src.models import OrganizationRecord
from src.modules.project.infra.db_models import ProjectRecord, ProjectScheduleRecord
from src.modules.user.infra.db_models import UserRecord

pytestmark = pytest.mark.asyncio


async def _create_scheduled_project(session, *, suffix: str, project_name: str) -> ProjectRecord:
    organization = OrganizationRecord(name=f"Scheduled projects org {project_name} {suffix}")
    session.add(organization)
    await session.flush()
    user = UserRecord(
        email=f"scheduled-{project_name.lower().replace(' ', '-')}-{suffix}@example.com",
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
        name=project_name,
        user_id=user.id,
        organization_id=organization.id,
    )
    session.add(project)
    await session.flush()
    session.add(
        ProjectScheduleRecord(
            project_id=project.id,
            scheduled_by_user_id=user.id,
            cron="0 * * * *",
            disabled=True,
        )
    )
    return project


async def test_get_scheduled_projects_returns_project_names(
    test_db_async_engine,
    monkeypatch,
) -> None:
    session_factory = async_sessionmaker(test_db_async_engine, expire_on_commit=False)
    suffix = uuid4().hex
    async with session_factory() as session:
        project = await _create_scheduled_project(
            session, suffix=suffix, project_name="Nightly import"
        )
        other_project = await _create_scheduled_project(
            session, suffix=suffix, project_name="Other org export"
        )
        await session.commit()

    monkeypatch.setattr(project_scheduler_module, "engine", test_db_async_engine)
    manager = ProjectSchedulerManager()

    schedules = await manager.get_scheduled_projects(organization_id=project.organization_id)
    assert [(item.project_id, item.project_name) for item in schedules] == [
        (project.id, "Nightly import"),
    ]

    single = await manager.get_scheduled_project(other_project.id)
    assert single is not None
    assert single.project_name == "Other org export"
