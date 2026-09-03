from __future__ import annotations

import pytest

from src.crud.organization.delete import (
    delete_organization,
    get_organization_dependency_counts,
    organization_has_dependencies,
)
from src.crud.organization.read import get_projects_count_by_organization_ids
from src.enums import DVTDefaultRoles
from src.models import OrganizationRecord
from src.modules.project.infra.db_models import ProjectRecord
from src.modules.user.infra.db_models import UserRecord


@pytest.mark.asyncio
async def test_delete_organization_removes_record(test_db_session) -> None:
    organization = OrganizationRecord(name="Disposable org")
    test_db_session.add(organization)
    test_db_session.commit()

    await delete_organization(test_db_session, organization)
    test_db_session.commit()

    assert test_db_session.get(OrganizationRecord, organization.id) is None


@pytest.mark.asyncio
async def test_organization_has_dependencies_detects_related_entities(test_db_session) -> None:
    organization = OrganizationRecord(name="Dependent org")
    test_db_session.add(organization)
    test_db_session.commit()
    user = UserRecord(
        email="dependent@example.com",
        hashed_password="hashed",
        auth_provider="email",
        is_verified=True,
        is_active=True,
        role=DVTDefaultRoles.USER.value,
        organization_id=organization.id,
    )
    test_db_session.add(user)
    test_db_session.commit()

    dependency_counts = await get_organization_dependency_counts(
        test_db_session,
        organization_id=organization.id,
    )

    assert dependency_counts["users"] == 1
    assert await organization_has_dependencies(test_db_session, organization_id=organization.id) is True


@pytest.mark.asyncio
async def test_get_projects_count_by_organization_ids_counts_only_not_deleted_projects(test_db_session) -> None:
    first_organization = OrganizationRecord(name="First org")
    second_organization = OrganizationRecord(name="Second org")
    test_db_session.add_all([first_organization, second_organization])
    test_db_session.commit()

    first_user = UserRecord(
        email="first-org-user@example.com",
        hashed_password="hashed",
        auth_provider="email",
        is_verified=True,
        is_active=True,
        role=DVTDefaultRoles.USER.value,
        organization_id=first_organization.id,
    )
    second_user = UserRecord(
        email="second-org-user@example.com",
        hashed_password="hashed",
        auth_provider="email",
        is_verified=True,
        is_active=True,
        role=DVTDefaultRoles.USER.value,
        organization_id=second_organization.id,
    )
    test_db_session.add_all([first_user, second_user])
    test_db_session.commit()

    test_db_session.add_all(
        [
            ProjectRecord(name="First active", user_id=first_user.id, organization_id=first_organization.id),
            ProjectRecord(name="First deleted", user_id=first_user.id, organization_id=first_organization.id, is_deleted=True),
            ProjectRecord(name="Second active", user_id=second_user.id, organization_id=second_organization.id),
        ]
    )
    test_db_session.commit()

    counts = await get_projects_count_by_organization_ids(
        test_db_session,
        organization_ids=[first_organization.id, second_organization.id, "missing-org"],
    )

    assert counts[first_organization.id] == 1
    assert counts[second_organization.id] == 1
    assert counts["missing-org"] == 0
