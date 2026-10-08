from unittest.mock import AsyncMock

import pytest

from src.crud.project import project_variables as project_variables_module
from src.enums import DVTDefaultRoles
from src.models import OrganizationRecord
from src.modules.project.infra.db_models import ProjectRecord
from src.modules.user.infra.db_models import UserRecord


async def _seed(session):
    organization = OrganizationRecord(name="Org")
    session.add(organization)
    await session.flush()
    user = UserRecord(
        email="owner@example.com",
        hashed_password="h",
        auth_provider="email",
        is_verified=True,
        is_active=True,
        role=DVTDefaultRoles.USER.value,
        organization_id=organization.id,
    )
    session.add(user)
    await session.flush()
    project = ProjectRecord(id="p1", name="P", user_id=user.id, organization_id=organization.id)
    session.add(project)
    await session.commit()
    return project, user


@pytest.mark.asyncio
async def test_variable_mutations_notify_catalog_after_commit(async_test_db_session, monkeypatch):
    project, user = await _seed(async_test_db_session)
    notify = AsyncMock()
    monkeypatch.setattr(project_variables_module, "on_project_variables_changed", notify)

    await project_variables_module.set_variables(
        async_test_db_session,
        project.id,
        {"tbl": {"type": "STRING", "value": "orders", "is_list_type": False}},
        user,
    )
    await project_variables_module.delete_variable(async_test_db_session, project.id, "tbl", user)

    assert notify.await_count == 2
    notify.assert_awaited_with(
        session=async_test_db_session,
        project_id=project.id,
        organization_id=project.organization_id,
    )


@pytest.mark.asyncio
async def test_catalog_failure_does_not_break_variable_update(async_test_db_session, monkeypatch):
    project, user = await _seed(async_test_db_session)
    monkeypatch.setattr(
        project_variables_module,
        "on_project_variables_changed",
        AsyncMock(side_effect=RuntimeError("catalog down")),
    )

    result = await project_variables_module.set_variables(
        async_test_db_session,
        project.id,
        {"tbl": {"type": "STRING", "value": "orders", "is_list_type": False}},
        user,
    )

    assert [item.key for item in result] == ["tbl"]
    refreshed = await async_test_db_session.get(ProjectRecord, project.id)
    assert "tbl" in (refreshed.variables or {})
