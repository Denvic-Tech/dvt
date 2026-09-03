from __future__ import annotations

import pytest
from usrak.core.dependencies.user import get_optional_user_any

from services.gateway.routes.organization import crud as organization_crud
from services.gateway.routes.public.organization import crud as public_organization_crud

from src.enums import DVTDefaultRoles
from src.models import OrganizationRecord
from src.modules.project.infra.db_models import ProjectRecord
from src.modules.user.infra.db_models import UserRecord
from src.modules.user.infra.fastapi.dependencies import get_user_access_only


def _create_user(
    session,
    *,
    email: str,
    role: str,
    organization_id: str,
) -> UserRecord:
    user = UserRecord(
        email=email,
        hashed_password="hashed",
        auth_provider="email",
        is_verified=True,
        is_active=True,
        role=role,
        organization_id=organization_id,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@pytest.fixture
def other_organization(db_session) -> OrganizationRecord:
    organization = OrganizationRecord(name="Other organization", inn="5555555555")
    db_session.add(organization)
    db_session.commit()
    db_session.refresh(organization)
    return organization


@pytest.fixture
def empty_organization(db_session) -> OrganizationRecord:
    organization = OrganizationRecord(name="Empty organization", inn="6666666666")
    db_session.add(organization)
    db_session.commit()
    db_session.refresh(organization)
    return organization


@pytest.fixture
def superadmin_user(db_session, test_organization) -> UserRecord:
    return _create_user(
        db_session,
        email="superadmin@example.com",
        role=DVTDefaultRoles.SUPERADMIN.value,
        organization_id=test_organization.id,
    )


@pytest.fixture
def dependent_other_org_user(db_session, other_organization) -> UserRecord:
    return _create_user(
        db_session,
        email="dependent-other@example.com",
        role=DVTDefaultRoles.USER.value,
        organization_id=other_organization.id,
    )


@pytest.fixture
def set_current_user(gateway_client):
    from services.gateway.main import app

    def _set(user: UserRecord) -> None:
        app.dependency_overrides[get_user_access_only] = lambda: user
        app.dependency_overrides[get_optional_user_any] = lambda: user
        app.dependency_overrides[organization_crud._get_user] = lambda: user
        app.dependency_overrides[public_organization_crud._get_user] = lambda: user

    return _set


@pytest.mark.asyncio
async def test_superadmin_lists_all_organizations(
    gateway_client,
    router_prefix,
    set_current_user,
    superadmin_user,
    other_organization,
    empty_organization,
    db_session,
):
    set_current_user(superadmin_user)
    own_project = ProjectRecord(
        name="Own organization project",
        user_id=superadmin_user.id,
        organization_id=superadmin_user.organization_id,
    )
    other_user = _create_user(
        db_session,
        email="other-org-project-owner@example.com",
        role=DVTDefaultRoles.USER.value,
        organization_id=other_organization.id,
    )
    other_project = ProjectRecord(
        name="Other organization project",
        user_id=other_user.id,
        organization_id=other_organization.id,
    )
    db_session.add_all([own_project, other_project])
    db_session.commit()

    response = await gateway_client.get(f"{router_prefix}/organizations")

    assert response.status_code == 200
    payload = response.json()
    assert {item["id"] for item in payload} >= {
        superadmin_user.organization_id,
        other_organization.id,
        empty_organization.id,
    }
    counts_by_id = {item["id"]: item["projects_count"] for item in payload}
    assert counts_by_id[superadmin_user.organization_id] == 1
    assert counts_by_id[other_organization.id] == 1
    assert counts_by_id[empty_organization.id] == 0


@pytest.mark.asyncio
async def test_admin_lists_only_own_organization(
    gateway_client,
    router_prefix,
    set_current_user,
    test_admin_user,
    other_organization,
    db_session,
):
    set_current_user(test_admin_user)
    own_project = ProjectRecord(
        name="Admin own project",
        user_id=test_admin_user.id,
        organization_id=test_admin_user.organization_id,
    )
    other_user = _create_user(
        db_session,
        email="admin-foreign-org-owner@example.com",
        role=DVTDefaultRoles.USER.value,
        organization_id=other_organization.id,
    )
    other_project = ProjectRecord(
        name="Other org project",
        user_id=other_user.id,
        organization_id=other_organization.id,
    )
    db_session.add_all([own_project, other_project])
    db_session.commit()

    response = await gateway_client.get(f"{router_prefix}/organizations")

    assert response.status_code == 200
    payload = response.json()
    assert [item["id"] for item in payload] == [test_admin_user.organization_id]
    assert payload[0]["projects_count"] == 1


@pytest.mark.asyncio
async def test_user_can_get_only_own_organization(
    gateway_client,
    router_prefix,
    set_current_user,
    test_user,
    other_organization,
    test_user_project,
):
    set_current_user(test_user)

    own_response = await gateway_client.get(f"{router_prefix}/organizations/{test_user.organization_id}")
    foreign_response = await gateway_client.get(f"{router_prefix}/organizations/{other_organization.id}")

    assert own_response.status_code == 200
    assert own_response.json()["id"] == test_user.organization_id
    assert own_response.json()["projects_count"] == 1
    assert foreign_response.status_code == 404


@pytest.mark.asyncio
async def test_superadmin_can_get_foreign_organization_with_projects_count(
    gateway_client,
    router_prefix,
    set_current_user,
    superadmin_user,
    other_organization,
    db_session,
):
    set_current_user(superadmin_user)
    other_user = _create_user(
        db_session,
        email="single-org-project-owner@example.com",
        role=DVTDefaultRoles.USER.value,
        organization_id=other_organization.id,
    )
    project = ProjectRecord(
        name="Foreign organization project",
        user_id=other_user.id,
        organization_id=other_organization.id,
    )
    db_session.add(project)
    db_session.commit()

    response = await gateway_client.get(f"{router_prefix}/organizations/{other_organization.id}")

    assert response.status_code == 200
    assert response.json()["id"] == other_organization.id
    assert response.json()["projects_count"] == 1


@pytest.mark.asyncio
async def test_projects_count_excludes_soft_deleted_projects(
    gateway_client,
    router_prefix,
    set_current_user,
    test_admin_user,
    db_session,
):
    set_current_user(test_admin_user)
    active_project = ProjectRecord(
        name="Active project",
        user_id=test_admin_user.id,
        organization_id=test_admin_user.organization_id,
        is_deleted=False,
    )
    deleted_project = ProjectRecord(
        name="Deleted project",
        user_id=test_admin_user.id,
        organization_id=test_admin_user.organization_id,
        is_deleted=True,
    )
    db_session.add_all([active_project, deleted_project])
    db_session.commit()

    response = await gateway_client.get(f"{router_prefix}/organizations")

    assert response.status_code == 200
    assert response.json()[0]["projects_count"] == 1


@pytest.mark.asyncio
async def test_superadmin_can_create_organization(
    gateway_client,
    router_prefix,
    set_current_user,
    superadmin_user,
):
    set_current_user(superadmin_user)

    response = await gateway_client.post(
        f"{router_prefix}/organizations",
        json={
            "name": "Created org",
            "description": "Created description",
            "inn": "7777777777",
            "is_active": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["name"] == "Created org"
    assert payload["inn"] == "7777777777"


@pytest.mark.asyncio
async def test_admin_cannot_create_organization(
    gateway_client,
    router_prefix,
    set_current_user,
    test_admin_user,
):
    set_current_user(test_admin_user)

    response = await gateway_client.post(
        f"{router_prefix}/organizations",
        json={"name": "Forbidden org", "is_active": True},
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_update_only_own_organization(
    gateway_client,
    router_prefix,
    set_current_user,
    test_admin_user,
    other_organization,
):
    set_current_user(test_admin_user)

    own_response = await gateway_client.patch(
        f"{router_prefix}/organizations/{test_admin_user.organization_id}",
        json={"description": "Updated by admin"},
    )
    foreign_response = await gateway_client.patch(
        f"{router_prefix}/organizations/{other_organization.id}",
        json={"description": "No access"},
    )

    assert own_response.status_code == 200
    assert own_response.json()["description"] == "Updated by admin"
    assert foreign_response.status_code == 404


@pytest.mark.asyncio
async def test_user_cannot_update_own_organization(
    gateway_client,
    router_prefix,
    set_current_user,
    test_user,
):
    set_current_user(test_user)

    response = await gateway_client.patch(
        f"{router_prefix}/organizations/{test_user.organization_id}",
        json={"description": "Should fail"},
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_superadmin_cannot_delete_own_organization(
    gateway_client,
    router_prefix,
    set_current_user,
    superadmin_user,
):
    set_current_user(superadmin_user)

    response = await gateway_client.delete(
        f"{router_prefix}/organizations/{superadmin_user.organization_id}"
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_superadmin_cannot_delete_organization_with_dependencies(
    gateway_client,
    router_prefix,
    set_current_user,
    superadmin_user,
    other_organization,
    dependent_other_org_user,
):
    set_current_user(superadmin_user)

    response = await gateway_client.delete(f"{router_prefix}/organizations/{other_organization.id}")

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_superadmin_can_delete_empty_organization(
    gateway_client,
    router_prefix,
    set_current_user,
    superadmin_user,
    empty_organization,
):
    set_current_user(superadmin_user)

    delete_response = await gateway_client.delete(
        f"{router_prefix}/organizations/{empty_organization.id}"
    )
    get_response = await gateway_client.get(f"{router_prefix}/organizations/{empty_organization.id}")

    assert delete_response.status_code == 200
    assert delete_response.json()["success"] is True
    assert get_response.status_code == 404


@pytest.mark.asyncio
async def test_superadmin_update_rejects_duplicate_inn(
    gateway_client,
    router_prefix,
    set_current_user,
    superadmin_user,
    other_organization,
    db_session,
):
    set_current_user(superadmin_user)
    duplicate_organization = OrganizationRecord(name="Duplicate org", inn="8888888888")
    db_session.add(duplicate_organization)
    db_session.commit()
    db_session.refresh(duplicate_organization)

    response = await gateway_client.patch(
        f"{router_prefix}/organizations/{other_organization.id}",
        json={"inn": "8888888888"},
    )

    assert response.status_code == 409
