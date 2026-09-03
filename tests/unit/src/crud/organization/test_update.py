from __future__ import annotations

import pytest

from src.crud.organization.exceptions import OrganizationINNConflictException
from src.crud.organization.update import update_organization
from src.models import OrganizationRecord


@pytest.mark.asyncio
async def test_update_organization_updates_fields(test_db_session) -> None:
    organization = OrganizationRecord(
        name="Original org",
        description="Original description",
        inn="1111111111",
        is_active=True,
    )
    test_db_session.add(organization)
    test_db_session.commit()

    updated = await update_organization(
        test_db_session,
        organization_id=organization.id,
        name="Updated org",
        description=None,
        inn=None,
        is_active=False,
    )

    assert updated is not None
    assert updated.name == "Updated org"
    assert updated.description is None
    assert updated.inn is None
    assert updated.is_active is False


@pytest.mark.asyncio
async def test_update_organization_raises_on_duplicate_inn(test_db_session) -> None:
    first = OrganizationRecord(name="First org", inn="1111111111")
    second = OrganizationRecord(name="Second org", inn="2222222222")
    test_db_session.add(first)
    test_db_session.add(second)
    test_db_session.commit()

    with pytest.raises(OrganizationINNConflictException):
        await update_organization(
            test_db_session,
            organization_id=second.id,
            inn="1111111111",
        )
