from __future__ import annotations

from datetime import UTC, datetime
import importlib

import pytest
from db_connection import ConnectionCheckResult, ConnectionNotFoundError, ValidationFailedError
from db_connection.domain import ConnectionRecord
from fastapi import status
from usrak.core.dependencies.user import get_optional_user_any

from services.gateway.routes.public.router import get_user_any_auth

from src.modules.user.infra.db_models import UserRecord
from src.modules.user.infra.fastapi.dependencies import get_user_access_only


def _build_connection_payload(
    *,
    name: str = "Test connection",
    organization_id: str | None = None,
    user_id: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": name,
        "kind": "sql",
        "type": "postgres",
        "driver": "psycopg",
        "properties": {
            "host": "localhost",
            "port": 5432,
            "username": "testuser",
            "database": "testdb",
        },
        "secrets": {
            "password": "testpass",
        },
    }
    if organization_id is not None:
        payload["organization_id"] = organization_id
    if user_id is not None:
        payload["user_id"] = user_id
    return payload


def _build_connection_record(
    *,
    connection_id: str = "conn-1",
    name: str = "Test connection",
    organization_id: str,
    user_id: str,
    deleted_at: datetime | None = None,
) -> ConnectionRecord:
    now = datetime.now(UTC)
    return ConnectionRecord(
        id=connection_id,
        name=name,
        kind="sql",
        type="postgres",
        driver="psycopg",
        driver_options=None,
        properties={
            "host": "localhost",
            "port": 5432,
            "username": "testuser",
            "database": "testdb",
        },
        secrets={"password": "testpass"},
        labels={"env": "test"},
        metadata={"team": "data"},
        extra={
            "organization_id": organization_id,
            "user_id": user_id,
        },
        created_at=now,
        updated_at=now,
        deleted_at=deleted_at,
    )


@pytest.fixture
def db_connection_service():
    public_router_module = importlib.import_module("services.gateway.routes.public.router")

    return public_router_module.public_db_connections_ext.runtime.service


@pytest.fixture
def set_current_user(gateway_client):
    from services.gateway.main import app

    def _set(user: UserRecord) -> None:
        app.dependency_overrides[get_user_access_only] = lambda: user
        app.dependency_overrides[get_optional_user_any] = lambda: user
        app.dependency_overrides[get_user_any_auth] = lambda: user

    return _set


@pytest.mark.asyncio
async def test_get_db_connections_success(
    gateway_client,
    router_prefix,
    set_current_user,
    test_admin_user,
    db_connection_service,
    monkeypatch,
):
    set_current_user(test_admin_user)

    async def mock_list(query, *, actor, uow=None):
        assert query.type is None
        assert actor.id == test_admin_user.id
        return [
            _build_connection_record(
                organization_id=test_admin_user.organization_id,
                user_id=test_admin_user.id,
            )
        ]

    monkeypatch.setattr(db_connection_service, "list", mock_list)

    response = await gateway_client.get(f"{router_prefix}/public/db-connections")

    assert response.status_code == status.HTTP_200_OK
    assert response.json()[0]["type"] == "postgres"
    assert response.json()[0]["kind"] == "sql"


@pytest.mark.asyncio
async def test_get_db_connection_by_id_success(
    gateway_client,
    router_prefix,
    set_current_user,
    test_admin_user,
    db_connection_service,
    monkeypatch,
):
    set_current_user(test_admin_user)

    async def mock_get(connection_id, *, actor, uow=None):
        assert connection_id == "conn-1"
        assert actor.id == test_admin_user.id
        return _build_connection_record(
            connection_id=connection_id,
            organization_id=test_admin_user.organization_id,
            user_id=test_admin_user.id,
        )

    monkeypatch.setattr(db_connection_service, "get", mock_get)

    response = await gateway_client.get(f"{router_prefix}/public/db-connections/conn-1")

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["id"] == "conn-1"


@pytest.mark.asyncio
async def test_get_db_connection_by_id_not_found(
    gateway_client,
    router_prefix,
    set_current_user,
    test_admin_user,
    db_connection_service,
    monkeypatch,
):
    set_current_user(test_admin_user)

    async def mock_get(connection_id, *, actor, uow=None):
        raise ConnectionNotFoundError(connection_id)

    monkeypatch.setattr(db_connection_service, "get", mock_get)

    response = await gateway_client.get(f"{router_prefix}/public/db-connections/non-existent")

    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_create_db_connection_success(
    gateway_client,
    router_prefix,
    set_current_user,
    test_admin_user,
    db_connection_service,
    monkeypatch,
):
    set_current_user(test_admin_user)

    async def mock_create(draft, *, actor, uow=None):
        assert draft.kind == "sql"
        assert draft.type == "postgres"
        assert draft.properties["database"] == "testdb"
        assert draft.secrets["password"] == "testpass"
        return _build_connection_record(
            organization_id=actor.organization_id,
            user_id=actor.id,
            name=draft.name,
        )

    monkeypatch.setattr(db_connection_service, "create", mock_create)

    response = await gateway_client.post(
        f"{router_prefix}/public/db-connections",
        json=_build_connection_payload(name="New Test Connection"),
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["name"] == "New Test Connection"


@pytest.mark.asyncio
async def test_create_db_connection_superadmin_can_override_owner(
    gateway_client,
    router_prefix,
    set_current_user,
    test_superadmin_user,
    test_user,
    db_connection_service,
    monkeypatch,
):
    set_current_user(test_superadmin_user)

    async def mock_create(draft, *, actor, uow=None):
        owner_org = draft.extra.get("organization_id", actor.organization_id)
        owner_user = draft.extra.get("user_id", actor.id)
        return _build_connection_record(
            organization_id=owner_org,
            user_id=owner_user,
            name=draft.name,
        )

    monkeypatch.setattr(db_connection_service, "create", mock_create)

    response = await gateway_client.post(
        f"{router_prefix}/public/db-connections",
        json=_build_connection_payload(
            name="Superadmin Owned Connection",
            organization_id=test_user.organization_id,
            user_id=test_user.id,
        ),
    )

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["organization_id"] == test_user.organization_id
    assert data["user_id"] == test_user.id


@pytest.mark.asyncio
async def test_create_db_connection_admin_forces_current_owner(
    gateway_client,
    router_prefix,
    set_current_user,
    test_admin_user,
    test_organization_supuradmin,
    db_connection_service,
    monkeypatch,
):
    set_current_user(test_admin_user)

    async def mock_create(draft, *, actor, uow=None):
        owner_org = actor.organization_id
        owner_user = actor.id
        return _build_connection_record(
            organization_id=owner_org,
            user_id=owner_user,
            name=draft.name,
        )

    monkeypatch.setattr(db_connection_service, "create", mock_create)

    response = await gateway_client.post(
        f"{router_prefix}/public/db-connections",
        json=_build_connection_payload(
            name="Admin Forced Owner Connection",
            organization_id=test_organization_supuradmin.id,
            user_id="foreign-user",
        ),
    )

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["organization_id"] == test_admin_user.organization_id
    assert data["user_id"] == test_admin_user.id


@pytest.mark.asyncio
async def test_create_db_connection_without_required_fields(
    gateway_client,
    router_prefix,
    set_current_user,
    test_admin_user,
):
    set_current_user(test_admin_user)

    response = await gateway_client.post(
        f"{router_prefix}/public/db-connections",
        json={"name": "Broken connection", "type": "postgres"},
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
async def test_update_db_connection_success(
    gateway_client,
    router_prefix,
    set_current_user,
    test_admin_user,
    db_connection_service,
    monkeypatch,
):
    set_current_user(test_admin_user)

    async def mock_update(connection_id, patch, *, actor, uow=None):
        assert connection_id == "conn-1"
        assert patch.name == "Updated connection"
        return _build_connection_record(
            connection_id=connection_id,
            organization_id=actor.organization_id,
            user_id=actor.id,
            name=patch.name,
        )

    monkeypatch.setattr(db_connection_service, "update", mock_update)

    response = await gateway_client.patch(
        f"{router_prefix}/public/db-connections/conn-1",
        json={"name": "Updated connection"},
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["name"] == "Updated connection"


@pytest.mark.asyncio
async def test_update_db_connection_superadmin_can_override_owner(
    gateway_client,
    router_prefix,
    set_current_user,
    test_superadmin_user,
    test_user,
    db_connection_service,
    monkeypatch,
):
    set_current_user(test_superadmin_user)

    async def mock_update(connection_id, patch, *, actor, uow=None):
        owner_org = patch.extra.get("organization_id", actor.organization_id)
        owner_user = patch.extra.get("user_id", actor.id)
        return _build_connection_record(
            connection_id=connection_id,
            organization_id=owner_org,
            user_id=owner_user,
            name="User Owned Connection",
        )

    monkeypatch.setattr(db_connection_service, "update", mock_update)

    response = await gateway_client.patch(
        f"{router_prefix}/public/db-connections/conn-1",
        json={
            "organization_id": test_user.organization_id,
            "user_id": test_user.id,
        },
    )

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["organization_id"] == test_user.organization_id
    assert data["user_id"] == test_user.id


@pytest.mark.asyncio
async def test_update_db_connection_admin_forces_current_owner(
    gateway_client,
    router_prefix,
    set_current_user,
    test_admin_user,
    test_organization_supuradmin,
    db_connection_service,
    monkeypatch,
):
    set_current_user(test_admin_user)

    async def mock_update(connection_id, patch, *, actor, uow=None):
        return _build_connection_record(
            connection_id=connection_id,
            organization_id=actor.organization_id,
            user_id=actor.id,
            name="Admin-owned connection",
        )

    monkeypatch.setattr(db_connection_service, "update", mock_update)

    response = await gateway_client.patch(
        f"{router_prefix}/public/db-connections/conn-1",
        json={
            "organization_id": test_organization_supuradmin.id,
            "user_id": "foreign-user",
        },
    )

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["organization_id"] == test_admin_user.organization_id
    assert data["user_id"] == test_admin_user.id


@pytest.mark.asyncio
async def test_update_db_connection_not_found(
    gateway_client,
    router_prefix,
    set_current_user,
    test_admin_user,
    db_connection_service,
    monkeypatch,
):
    set_current_user(test_admin_user)

    async def mock_update(connection_id, patch, *, actor, uow=None):
        raise ConnectionNotFoundError(connection_id)

    monkeypatch.setattr(db_connection_service, "update", mock_update)

    response = await gateway_client.patch(
        f"{router_prefix}/public/db-connections/non-existent",
        json={"name": "Updated non-existent"},
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_delete_db_connection_success(
    gateway_client,
    router_prefix,
    set_current_user,
    test_admin_user,
    db_connection_service,
    monkeypatch,
):
    set_current_user(test_admin_user)

    async def mock_delete(connection_id, *, actor, uow=None):
        assert connection_id == "conn-1"
        return _build_connection_record(
            connection_id=connection_id,
            organization_id=actor.organization_id,
            user_id=actor.id,
            deleted_at=datetime.now(UTC),
        )

    monkeypatch.setattr(db_connection_service, "delete", mock_delete)

    response = await gateway_client.delete(
        f"{router_prefix}/public/db-connections/conn-1"
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["deleted_at"] is not None


@pytest.mark.asyncio
async def test_delete_db_connection_not_found(
    gateway_client,
    router_prefix,
    set_current_user,
    test_admin_user,
    db_connection_service,
    monkeypatch,
):
    set_current_user(test_admin_user)

    async def mock_delete(connection_id, *, actor, uow=None):
        raise ConnectionNotFoundError(connection_id)

    monkeypatch.setattr(db_connection_service, "delete", mock_delete)

    response = await gateway_client.delete(
        f"{router_prefix}/public/db-connections/non-existent"
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_check_db_connection_success(
    gateway_client,
    router_prefix,
    set_current_user,
    test_admin_user,
    db_connection_service,
    monkeypatch,
):
    set_current_user(test_admin_user)

    async def mock_check_payload(draft, *, actor):
        assert draft.kind == "sql"
        assert draft.type == "postgres"
        return ConnectionCheckResult(
            name=draft.name,
            connected=True,
            message="Connection successful.",
        )

    monkeypatch.setattr(db_connection_service, "check_payload", mock_check_payload)

    response = await gateway_client.post(
        f"{router_prefix}/public/db-connections/check",
        json=_build_connection_payload(name="Check connection"),
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["connected"] is True


@pytest.mark.asyncio
async def test_check_db_connection_by_id_success(
    gateway_client,
    router_prefix,
    set_current_user,
    test_admin_user,
    db_connection_service,
    monkeypatch,
):
    set_current_user(test_admin_user)

    async def mock_check_stored(connection_id, *, actor, patch=None, uow=None):
        assert connection_id == "conn-1"
        assert patch is not None
        assert patch.name == "Check + Update Name"
        return ConnectionCheckResult(
            name="Check + Update Name",
            connected=True,
            message="Connection successful.",
        )

    monkeypatch.setattr(db_connection_service, "check_stored", mock_check_stored)

    response = await gateway_client.post(
        f"{router_prefix}/public/db-connections/conn-1/check",
        json={"name": "Check + Update Name"},
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["name"] == "Check + Update Name"


@pytest.mark.asyncio
async def test_check_db_connection_by_id_not_found(
    gateway_client,
    router_prefix,
    set_current_user,
    test_admin_user,
    db_connection_service,
    monkeypatch,
):
    set_current_user(test_admin_user)

    async def mock_check_stored(connection_id, *, actor, patch=None, uow=None):
        raise ConnectionNotFoundError(connection_id)

    monkeypatch.setattr(db_connection_service, "check_stored", mock_check_stored)

    response = await gateway_client.post(
        f"{router_prefix}/public/db-connections/non-existent/check",
        json={},
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_create_db_connection_returns_validation_error_from_service(
    gateway_client,
    router_prefix,
    set_current_user,
    test_admin_user,
    db_connection_service,
    monkeypatch,
):
    set_current_user(test_admin_user)

    async def mock_create(draft, *, actor, uow=None):
        raise ValidationFailedError("Invalid connection settings.")

    monkeypatch.setattr(db_connection_service, "create", mock_create)

    response = await gateway_client.post(
        f"{router_prefix}/public/db-connections",
        json=_build_connection_payload(),
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert "Invalid connection settings." in str(response.json())
