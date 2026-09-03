from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.crud.admin.user import delete as delete_module
from src.models import OrganizationRecord
from src.modules.user.infra.db_models import UserRecord


class _ScalarResult:
    def __init__(self, values):
        self._values = values

    def all(self):
        return self._values


def _make_user(email: str) -> UserRecord:
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
async def test_delete_users_soft_deletes_and_flushes() -> None:
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    users = [_make_user("one@example.com"), _make_user("two@example.com")]

    deleted = await delete_module.delete_users(session, users)

    assert list(deleted) == users
    stmt = session.execute.await_args.args[0]
    params = stmt.compile().params

    assert params["is_active"] is False
    assert set(params["id_1"]) == {user.id for user in users}
    session.add.assert_not_called()
    session.flush.assert_awaited_once_with()
    assert session.refresh.await_count == 2


@pytest.mark.asyncio
async def test_delete_users_by_returns_deleted_ids(monkeypatch) -> None:
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    users = [_make_user("one@example.com"), _make_user("two@example.com")]

    monkeypatch.setattr(
        delete_module,
        "get_users_by",
        AsyncMock(return_value=_ScalarResult(users)),
    )

    deleted_ids = await delete_module.delete_users_by(
        session,
        organization_id="org-1",
        email_contains="example",
    )

    assert deleted_ids == [user.id for user in users]
    stmt = session.execute.await_args.args[0]
    params = stmt.compile().params

    assert params["is_active"] is False
    assert set(params["id_1"]) == {user.id for user in users}
    session.add.assert_not_called()
    session.flush.assert_awaited_once_with()
    assert session.refresh.await_count == 2
