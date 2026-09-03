from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.crud.admin.user import update as update_module
from src.models import OrganizationRecord
from src.modules.user.infra.db_models import UserRecord


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def first(self):
        return self._value


def _make_user() -> UserRecord:
    organization = OrganizationRecord(name="Test org")
    return UserRecord(
        email="user@example.com",
        user_name="user",
        hashed_password="hashed",
        auth_provider="email",
        is_verified=True,
        is_active=True,
        role="user",
        organization_id=organization.id,
    )


@pytest.mark.asyncio
async def test_update_user_returns_none_when_missing(monkeypatch) -> None:
    session = AsyncMock()
    monkeypatch.setattr(
        update_module,
        "get_users_by",
        AsyncMock(return_value=_ScalarResult(None)),
    )

    user = await update_module.update_user(session, user_id="missing")

    assert user is None


@pytest.mark.asyncio
async def test_update_user_updates_fields_and_password_metadata(monkeypatch) -> None:
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    user = _make_user()
    old_version = user.password_version

    monkeypatch.setattr(
        update_module,
        "get_users_by",
        AsyncMock(return_value=_ScalarResult(user)),
    )

    updated_user = await update_module.update_user(
        session,
        user_id=user.id,
        email="updated@example.com",
        username="updated-user",
        password="secret",
        role="admin",
        is_active=False,
        is_verified=False,
        organization_id="org-2",
    )

    assert updated_user is user
    stmt = session.execute.await_args.args[0]
    params = stmt.compile().params

    assert params["email"] == "updated@example.com"
    assert params["user_name"] == "updated-user"
    assert params["role"] == "admin"
    assert params["is_active"] is False
    assert params["is_verified"] is False
    assert params["organization_id"] == "org-2"
    assert params["password_version"] == old_version + 1
    assert params["last_password_change"] is not None
    assert params["hashed_password"] != "secret"
    assert params["id_1"] == user.id
    session.add.assert_not_called()
    session.flush.assert_awaited_once_with()
    session.refresh.assert_awaited_once_with(user)
