from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.crud.project.update import (
    clear_project_graph_dirty_if_revision,
    mark_project_graph_dirty,
    touch_project_updated_at,
)
from src.enums import DVTDefaultRoles
from src.models import OrganizationRecord
from src.modules.project.infra.db_models import ProjectRecord
from src.modules.user.infra.db_models import UserRecord as UserModel


async def _create_project(
    session,
    *,
    project_id: str,
    is_deleted: bool = False,
) -> ProjectRecord:
    organization = OrganizationRecord(name=f"Organization {project_id}")
    session.add(organization)
    await session.commit()
    await session.refresh(organization)

    user = UserModel(
        email=f"{project_id}@example.com",
        hashed_password="hashed",
        auth_provider="email",
        is_verified=True,
        is_active=True,
        role=DVTDefaultRoles.USER.value,
        organization_id=organization.id,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)

    project = ProjectRecord(
        id=project_id,
        name=f"Project {project_id}",
        user_id=user.id,
        organization_id=organization.id,
        is_deleted=is_deleted,
        updated_at=datetime(2020, 1, 1, tzinfo=UTC),
    )
    session.add(project)
    await session.commit()
    await session.refresh(project)
    return project


@pytest.mark.asyncio
async def test_touch_project_updated_at_updates_active_project(async_test_db_session) -> None:
    project = await _create_project(async_test_db_session, project_id="project-active")
    previous_updated_at = project.updated_at

    touched = await touch_project_updated_at(
        async_test_db_session,
        project_id=project.id,
        organization_id=project.organization_id,
    )
    await async_test_db_session.commit()
    await async_test_db_session.refresh(project)

    assert touched is True
    assert project.updated_at > previous_updated_at


@pytest.mark.asyncio
async def test_touch_project_updated_at_ignores_deleted_project(async_test_db_session) -> None:
    project = await _create_project(
        async_test_db_session,
        project_id="project-deleted",
        is_deleted=True,
    )
    previous_updated_at = project.updated_at

    touched = await touch_project_updated_at(
        async_test_db_session,
        project_id=project.id,
        organization_id=project.organization_id,
    )
    await async_test_db_session.commit()
    await async_test_db_session.refresh(project)

    assert touched is False
    assert project.updated_at == previous_updated_at


@pytest.mark.asyncio
async def test_mark_and_clear_project_graph_dirty_is_revision_safe(async_test_db_session) -> None:
    project = await _create_project(async_test_db_session, project_id="project-dirty")
    project.dirty_node_ids = ["deleted-node", "old-node"]
    project.graph_revision = 3
    async_test_db_session.add(project)
    await async_test_db_session.commit()

    dirty_project = await mark_project_graph_dirty(
        async_test_db_session,
        project_id=project.id,
        organization_id=project.organization_id,
        node_ids=["new-node", "old-node"],
        removed_node_ids=["deleted-node"],
    )
    await async_test_db_session.commit()
    await async_test_db_session.refresh(project)

    assert dirty_project is project
    assert project.dirty_node_ids == ["new-node", "old-node"]
    assert project.graph_revision == 4

    cleared = await clear_project_graph_dirty_if_revision(
        async_test_db_session,
        project_id=project.id,
        graph_revision=3,
    )
    await async_test_db_session.commit()
    await async_test_db_session.refresh(project)
    assert cleared is False
    assert project.dirty_node_ids == ["new-node", "old-node"]

    cleared = await clear_project_graph_dirty_if_revision(
        async_test_db_session,
        project_id=project.id,
        graph_revision=4,
        node_ids=["old-node", "missing-node"],
    )
    await async_test_db_session.commit()
    await async_test_db_session.refresh(project)
    assert cleared is True
    assert project.dirty_node_ids == ["new-node"]

    cleared = await clear_project_graph_dirty_if_revision(
        async_test_db_session,
        project_id=project.id,
        graph_revision=4,
    )
    await async_test_db_session.commit()
    await async_test_db_session.refresh(project)
    assert cleared is True
    assert project.dirty_node_ids == []
