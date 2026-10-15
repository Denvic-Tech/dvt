from __future__ import annotations

from uuid import uuid4

import pytest

from src.enums import DVTDefaultRoles
from src.modules.project.infra.db_models import ProjectFavoriteRecord, ProjectRecord
from src.modules.user.infra.db_models import UserRecord


def _create_user(session, *, organization_id: str) -> UserRecord:
    user = UserRecord(
        email=f"user-{uuid4()}@example.com",
        hashed_password="hashed",
        auth_provider="email",
        is_verified=True,
        is_active=True,
        role=DVTDefaultRoles.USER.value,
        organization_id=organization_id,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def _create_project(session, *, user: UserRecord, name: str) -> ProjectRecord:
    project = ProjectRecord(
        id=str(uuid4()),
        name=name,
        user_id=user.id,
        organization_id=user.organization_id,
    )
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


@pytest.mark.asyncio
async def test_add_list_and_remove_favorite_project(
        gateway_client,
        router_prefix,
        test_user_project,
):
    project_id = test_user_project.id

    empty_resp = await gateway_client.get(f"{router_prefix}/projects/favorites")
    assert empty_resp.status_code == 200
    assert empty_resp.json() == []

    add_resp = await gateway_client.put(f"{router_prefix}/projects/{project_id}/favorite")
    assert add_resp.status_code == 200, add_resp.json()
    assert add_resp.json()["success"] is True

    # повторное добавление идемпотентно
    add_again_resp = await gateway_client.put(f"{router_prefix}/projects/{project_id}/favorite")
    assert add_again_resp.status_code == 200
    assert add_again_resp.json()["success"] is True

    favorites_resp = await gateway_client.get(f"{router_prefix}/projects/favorites")
    assert favorites_resp.status_code == 200
    favorites = favorites_resp.json()
    assert [item["id"] for item in favorites] == [project_id]
    assert favorites[0]["is_favorite"] is True

    list_resp = await gateway_client.get(f"{router_prefix}/projects")
    assert list_resp.status_code == 200
    listed = {item["id"]: item for item in list_resp.json()}
    assert listed[project_id]["is_favorite"] is True

    detail_resp = await gateway_client.get(f"{router_prefix}/projects/{project_id}")
    assert detail_resp.status_code == 200
    assert detail_resp.json()["is_favorite"] is True

    items_resp = await gateway_client.get(f"{router_prefix}/projects/items")
    assert items_resp.status_code == 200
    items = {
        item["project"]["id"]: item["project"]
        for item in items_resp.json()["items"]
        if item["type"] == "project"
    }
    assert items[project_id]["is_favorite"] is True

    remove_resp = await gateway_client.delete(f"{router_prefix}/projects/{project_id}/favorite")
    assert remove_resp.status_code == 200
    assert remove_resp.json()["success"] is True

    # повторное удаление идемпотентно
    remove_again_resp = await gateway_client.delete(f"{router_prefix}/projects/{project_id}/favorite")
    assert remove_again_resp.status_code == 200

    after_remove_resp = await gateway_client.get(f"{router_prefix}/projects/favorites")
    assert after_remove_resp.json() == []

    detail_after_resp = await gateway_client.get(f"{router_prefix}/projects/{project_id}")
    assert detail_after_resp.json()["is_favorite"] is False


@pytest.mark.asyncio
async def test_favorites_are_ordered_by_added_time_and_skip_deleted_projects(
        gateway_client,
        router_prefix,
        db_session,
        test_user,
):
    first = _create_project(db_session, user=test_user, name="First favorite")
    second = _create_project(db_session, user=test_user, name="Second favorite")
    deleted = _create_project(db_session, user=test_user, name="Deleted favorite")

    for project in (first, second, deleted):
        resp = await gateway_client.put(f"{router_prefix}/projects/{project.id}/favorite")
        assert resp.status_code == 200, resp.json()

    deleted.is_deleted = True
    db_session.add(deleted)
    db_session.commit()

    favorites_resp = await gateway_client.get(f"{router_prefix}/projects/favorites")
    assert favorites_resp.status_code == 200
    assert [item["id"] for item in favorites_resp.json()] == [second.id, first.id]


@pytest.mark.asyncio
async def test_favorites_are_personal_and_require_project_access(
        gateway_client,
        router_prefix,
        db_session,
        test_user,
        test_user_project,
):
    other_user = _create_user(db_session, organization_id=test_user.organization_id)
    other_project = _create_project(db_session, user=other_user, name="Other user project")

    db_session.add(
        ProjectFavoriteRecord(user_id=other_user.id, project_id=test_user_project.id)
    )
    db_session.commit()

    # чужая отметка не видна текущему пользователю
    favorites_resp = await gateway_client.get(f"{router_prefix}/projects/favorites")
    assert favorites_resp.status_code == 200
    assert favorites_resp.json() == []

    detail_resp = await gateway_client.get(f"{router_prefix}/projects/{test_user_project.id}")
    assert detail_resp.json()["is_favorite"] is False

    # недоступный проект нельзя добавить в избранное
    forbidden_resp = await gateway_client.put(f"{router_prefix}/projects/{other_project.id}/favorite")
    assert forbidden_resp.status_code == 404

    unknown_resp = await gateway_client.put(f"{router_prefix}/projects/{uuid4()}/favorite")
    assert unknown_resp.status_code == 404
