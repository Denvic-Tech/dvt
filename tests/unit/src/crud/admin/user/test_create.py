from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.crud.admin.user import create as create_module
from src.crud.admin import user as admin_user_crud
from src.models import OrganizationRecord
from src.modules.user.infra.db_models import UserRecord


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def first(self):
        return self._value


def _make_user(email: str = "existing@example.com") -> UserRecord:
    organization = OrganizationRecord(name="Test org")
    return UserRecord(
        email=email,
        hashed_password="hashed",
        auth_provider="email",
        is_verified=True,
        is_active=True,
        role="user",
        organization_id=organization.id,
    )


@pytest.mark.asyncio
async def test_create_user_creates_and_flushes_without_commit(monkeypatch) -> None:
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()

    monkeypatch.setattr(
        create_module.admin_user_crud,
        "get_users_by",
        AsyncMock(return_value=_ScalarResult(None)),
    )

    user = await create_module.create_user(
        session,
        email="new@example.com",
        username="new-user",
        password="secret",
        organization_id="org-1",
        role="admin",
    )

    assert user.email == "new@example.com"
    assert user.user_name == "new-user"
    assert user.organization_id == "org-1"
    assert user.role == "admin"
    session.add.assert_called_once_with(user)
    session.flush.assert_awaited_once_with([user])
    session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_create_user_raises_when_email_already_exists(monkeypatch) -> None:
    session = AsyncMock()
    monkeypatch.setattr(
        create_module.admin_user_crud,
        "get_users_by",
        AsyncMock(return_value=_ScalarResult(_make_user())),
    )

    with pytest.raises(admin_user_crud.UserAlreadyExistsException):
        await create_module.create_user(
            session,
            email="existing@example.com",
            username="existing",
            password="secret",
            organization_id="org-1",
        )
