from __future__ import annotations

import pytest

from src.crud.organization.read import get_organizations_by
from src.models import OrganizationRecord


@pytest.mark.asyncio
async def test_get_organizations_by_filters_by_id(test_db_session) -> None:
    first = OrganizationRecord(name="First org", inn="1111111111")
    second = OrganizationRecord(name="Second org", inn="2222222222")
    test_db_session.add(first)
    test_db_session.add(second)
    test_db_session.commit()

    organizations = (await get_organizations_by(test_db_session, organization_id=first.id)).all()

    assert [organization.id for organization in organizations] == [first.id]


@pytest.mark.asyncio
async def test_get_organizations_by_filters_by_inn(test_db_session) -> None:
    first = OrganizationRecord(name="First org", inn="1111111111")
    second = OrganizationRecord(name="Second org", inn="2222222222")
    test_db_session.add(first)
    test_db_session.add(second)
    test_db_session.commit()

    organization = (await get_organizations_by(test_db_session, inn="2222222222")).first()

    assert organization is not None
    assert organization.id == second.id

