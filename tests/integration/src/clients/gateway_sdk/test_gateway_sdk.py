from __future__ import annotations

from uuid import uuid4

import docker
import pytest

from src.clients.gateway_sdk import DVTClient


def _docker_available() -> bool:
    try:
        return bool(docker.from_env().ping())
    except Exception:
        return False


pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.docker_required,
    pytest.mark.skipif(not _docker_available(), reason="Docker daemon is unavailable"),
]


def _build_postgres_payload(postgres_container) -> dict:
    return {
        "name": f"sdk-postgres-{uuid4().hex[:8]}",
        "kind": "sql",
        "type": "postgres",
        "driver": "psycopg",
        "properties": {
            "host": postgres_container.get_container_host_ip(),
            "port": int(postgres_container.get_exposed_port(5432)),
            "username": postgres_container.username,
            "database": postgres_container.dbname,
        },
        "secrets": {
            "password": postgres_container.password,
        },
    }


async def test_gateway_sdk_private_db_connections_crud(
    gateway_live_base_url: str,
    gateway_setup_credentials: tuple[str, str],
    postgres_container,
) -> None:
    email, password = gateway_setup_credentials
    payload = _build_postgres_payload(postgres_container)
    client = DVTClient(
        base_url=f"{gateway_live_base_url}/api",
        username=email,
        password=password,
        timeout=30.0,
    )

    try:
        created = await client.db_connections.create(data=payload)
        listed = await client.db_connections.list(type="postgres")
        retrieved = await client.db_connections.retrieve(id=created.id)
        checked = await client.db_connections.check_by_id(connection_id=created.id, data={})
        deleted = await client.db_connections.delete(id=created.id)
    finally:
        await client.aclose()

    assert created.id
    assert any(item.id == created.id for item in listed)
    assert retrieved.id == created.id
    assert isinstance(checked.connected, bool)
    assert deleted.id == created.id
    assert deleted.deleted_at is not None


async def test_gateway_sdk_public_resources_with_api_token(
    gateway_live_base_url: str,
    gateway_auth_headers: dict[str, str],
    postgres_container,
) -> None:
    payload = _build_postgres_payload(postgres_container)
    token = gateway_auth_headers["X-API-Key"]
    client = DVTClient(
        base_url=f"{gateway_live_base_url}/api",
        api_token=token,
        timeout=30.0,
    )

    try:
        organizations = await client.public.organizations.list()
        created = await client.public.db_connections.create(data=payload)
        retrieved = await client.public.db_connections.retrieve(id=created.id)
        checked = await client.public.db_connections.check_by_id(
            connection_id=created.id,
            data={},
        )
        deleted = await client.public.db_connections.delete(id=created.id)
    finally:
        await client.aclose()

    assert organizations
    assert created.id
    assert retrieved.id == created.id
    assert isinstance(checked.connected, bool)
    assert deleted.id == created.id
