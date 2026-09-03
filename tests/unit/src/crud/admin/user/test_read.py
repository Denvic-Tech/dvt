from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.crud.admin.user.read import get_default_service_user, get_users_by
from src.crud.admin.user.exceptions import UserNotFoundException
from src.models import OrganizationRecord
from src.modules.user.infra.db_models import UserRecord


class _ScalarResult:
    def __init__(self, values):
        self._values = values

    def scalars(self):
        return self

    def first(self):
        if isinstance(self._values, list):
            return self._values[0] if self._values else None
        return self._values

    def all(self):
        if isinstance(self._values, list):
            return self._values
        return [] if self._values is None else [self._values]


def _make_user(*, email: str, role: str) -> UserRecord:
    organization = OrganizationRecord(name="Test org")
    return UserRecord(
        email=email,
        hashed_password="hashed",
        auth_provider="email",
        is_verified=True,
        is_active=True,
        role=role,
        organization_id=organization.id,
    )


@pytest.mark.asyncio
async def test_get_users_by_builds_expected_filters() -> None:
    session = AsyncMock()
    result = _ScalarResult([])
    session.execute = AsyncMock(return_value=result)

    returned = await get_users_by(
        session,
        user_id="user-1",
        email="user@example.com",
        user_name="user",
        role="admin",
        is_active=True,
        is_verified=False,
        organization_id="org-1",
        email_contains="example",
        limit=10,
        offset=20,
    )

    stmt = session.execute.await_args.args[0]
    sql = str(stmt)

    assert returned is result
    assert "users.id =" in sql
    assert "users.email =" in sql
    assert "users.user_name =" in sql
    assert "users.role =" in sql
    assert "users.is_active IS true" in sql
    assert "users.is_verified IS false" in sql
    assert "users.organization_id =" in sql
    assert "lower(users.email) LIKE lower" in sql
    assert "LIMIT" in sql
    assert "OFFSET" in sql


@pytest.mark.asyncio
async def test_get_default_service_user_returns_first_privileged_user() -> None:
    session = AsyncMock()
    expected_user = _make_user(email="superadmin@example.com", role="superadmin")
    session.execute = AsyncMock(return_value=_ScalarResult(expected_user))

    user = await get_default_service_user(session)

    assert user is expected_user
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_default_service_user_raises_when_no_privileged_users_found() -> None:
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_ScalarResult(None))

    with pytest.raises(UserNotFoundException):
        await get_default_service_user(session)
