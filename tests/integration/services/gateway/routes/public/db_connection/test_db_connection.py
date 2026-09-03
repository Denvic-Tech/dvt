from __future__ import annotations

import pytest
import httpx
import uuid
from typing import Any, Generator
from fastapi import status
from usrak.core.dependencies.user import get_optional_user_any

from services.gateway.routes.public.router import get_user_any_auth
from src.modules.user.infra.fastapi.dependencies import get_user_access_only

pytestmark = [pytest.mark.asyncio, pytest.mark.docker_required]


@pytest.fixture
async def auth_client(
    test_admin_user,
    test_db_session,
    gateway_app,
    gateway_http_client: httpx.AsyncClient,
    gateway_fixture_context,
) -> Generator[httpx.AsyncClient, None, None]:
    gateway_fixture_context.db_session = test_db_session
    gateway_fixture_context.user = test_admin_user
    gateway_app.dependency_overrides[get_user_access_only] = lambda: gateway_fixture_context.user
    gateway_app.dependency_overrides[get_optional_user_any] = lambda: gateway_fixture_context.user
    gateway_app.dependency_overrides[get_user_any_auth] = lambda: gateway_fixture_context.user

    yield gateway_http_client

    gateway_app.dependency_overrides.pop(get_user_access_only, None)
    gateway_app.dependency_overrides.pop(get_optional_user_any, None)
    gateway_app.dependency_overrides.pop(get_user_any_auth, None)
    gateway_fixture_context.user = None
    gateway_fixture_context.db_session = None


@pytest.mark.asyncio
async def test_get_db_connections_success(
    auth_client,
    postgres_db_connection,
):
    response = await auth_client.get("/api/public/db-connections")
    assert response.status_code == status.HTTP_200_OK
    assert isinstance(response.json(), list)


@pytest.mark.asyncio
async def test_get_db_connection_by_id_success(
    auth_client,
    postgres_db_connection,
):
    props = dict(postgres_db_connection.properties)
    secrets = dict(postgres_db_connection.secrets)
    create_data = {
        "name": "Integration Created Connection",
        "kind": "sql",
        "type": "postgres",
        "driver": "psycopg",
        "properties": props,
        "secrets": secrets,
    }
    response = await auth_client.post("/api/public/db-connections", json=create_data)
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    response = await auth_client.get(f"/api/public/db-connections/{data['id']}")
    assert response.status_code == status.HTTP_200_OK


@pytest.mark.asyncio
async def test_get_db_connection_by_id_not_found(
    auth_client,
):
    response = await auth_client.get(f"/api/public/db-connections/{uuid.uuid4()}")
    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_create_db_connection_success(
    auth_client,
    postgres_db_connection,
):
    props = dict(postgres_db_connection.properties)
    secrets = dict(postgres_db_connection.secrets)
    create_data = {
        "name": "Integration Created Connection",
        "kind": "sql",
        "type": "postgres",
        "driver": "psycopg",
        "properties": props,
        "secrets": secrets,
    }
    response = await auth_client.post("/api/public/db-connections", json=create_data)
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["name"] == create_data["name"]


@pytest.mark.asyncio
async def test_create_db_connection_without_required_fields(
    auth_client,
):
    response = await auth_client.post(
        "/api/public/db-connections",
        json={"properties": {"host": "localhost"}},
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
async def test_update_db_connection_not_found(
    auth_client,
):
    response = await auth_client.patch(
        f"/api/public/db-connections/{uuid.uuid4()}",
        json={"name": "Non-existent"},
    )
    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_delete_db_connection_success(
    auth_client,
    postgres_db_connection,
):
    props = dict(postgres_db_connection.properties)
    secrets = dict(postgres_db_connection.secrets)
    create_data = {
        "name": "Integration Created Connection",
        "kind": "sql",
        "type": "postgres",
        "driver": "psycopg",
        "properties": props,
        "secrets": secrets,
    }
    response = await auth_client.post("/api/public/db-connections", json=create_data)
    assert response.status_code == status.HTTP_200_OK
    data = response.json()

    response = await auth_client.delete(f"/api/public/db-connections/{data['id']}")
    assert response.status_code == status.HTTP_200_OK


@pytest.mark.asyncio
async def test_delete_db_connection_not_found(
    auth_client,
):
    response = await auth_client.delete(f"/api/public/db-connections/{uuid.uuid4()}")
    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_check_db_connection_by_id_not_found(
    auth_client,
):
    response = await auth_client.post(
        f"/api/public/db-connections/{uuid.uuid4()}/check",
        json={"name": "Whatever"},
    )
    assert response.status_code == status.HTTP_404_NOT_FOUND
