from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.crud.organization import create as create_module
from src.crud.organization.exceptions import OrganizationINNConflictException
from src.models import OrganizationRecord


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def first(self):
        return self._value


@pytest.mark.asyncio
async def test_create_organization_creates_and_flushes_without_commit(monkeypatch) -> None:
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()

    monkeypatch.setattr(
        create_module,
        "get_organizations_by",
        AsyncMock(return_value=_ScalarResult(None)),
    )

    organization = await create_module.create_organization(
        session,
        name="New org",
        description="Description",
        inn="1234567890",
        is_active=False,
    )

    assert organization.name == "New org"
    assert organization.description == "Description"
    assert organization.inn == "1234567890"
    assert organization.is_active is False
    session.add.assert_called_once_with(organization)
    session.flush.assert_awaited_once_with([organization])
    session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_create_organization_raises_when_inn_exists(monkeypatch) -> None:
    session = AsyncMock()
    existing = OrganizationRecord(name="Existing", inn="1234567890")
    monkeypatch.setattr(
        create_module,
        "get_organizations_by",
        AsyncMock(return_value=_ScalarResult(existing)),
    )

    with pytest.raises(OrganizationINNConflictException):
        await create_module.create_organization(
            session,
            name="New org",
            inn="1234567890",
        )
