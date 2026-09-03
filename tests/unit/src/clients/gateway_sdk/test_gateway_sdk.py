from __future__ import annotations

import httpx
import pytest

from src.clients.gateway_sdk import DVTAuthError, DVTClient, DVTSyncClient
from src.clients.gateway_sdk.generated.models import (
    CreateDatabaseRequest,
    CreateSchemaRequest,
    CreateTableFromSQLRequest,
    CreateTableFromSchemaRequest,
    GenerateSchemaDDLRequest,
    GenerateTableDDL,
)


async def _build_async_client(
    handler,
    **kwargs,
) -> DVTClient:
    client = DVTClient(base_url="http://testserver", timeout=5.0, **kwargs)
    await client._transport._client.aclose()
    client._transport._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://testserver",
    )
    return client


def _build_sync_client(
    handler,
    **kwargs,
) -> DVTSyncClient:
    client = DVTSyncClient(base_url="http://testserver", timeout=5.0, **kwargs)
    client._transport._client.close()
    client._transport._client = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="http://testserver",
    )
    return client


@pytest.mark.asyncio
async def test_transport_signs_in_and_uses_bearer_for_private_requests() -> None:
    seen_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        if request.url.path == "/auth/sign-in":
            assert request.method == "POST"
            assert request.headers.get("authorization") is None
            return httpx.Response(200, json={"success": True, "access_token": "token-123"})

        assert request.url.path == "/private"
        assert request.headers["authorization"] == "Bearer token-123"
        return httpx.Response(200, json={"ok": True})

    client = await _build_async_client(handler, username="user@example.com", password="Secret123")
    try:
        payload = await client._transport.request_json(
            method="GET",
            path="/private",
            response_type=dict[str, bool],
        )
    finally:
        await client.aclose()

    assert payload == {"ok": True}
    assert seen_paths == ["/auth/sign-in", "/private"]


@pytest.mark.asyncio
async def test_public_namespace_uses_api_token_and_private_request_returns_hint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/public/organizations":
            assert request.headers["x-api-key"] == "public-token"
            return httpx.Response(
                200,
                json=[{"id": "org-1", "name": "Org", "is_active": True}],
            )
        return httpx.Response(401, json={"detail": "Unauthorized"})

    client = await _build_async_client(handler, api_token="public-token")
    try:
        organizations = await client.public.organizations.list()
        assert organizations[0].name == "Org"

        with pytest.raises(DVTAuthError) as exc_info:
            await client._transport.request_json(
                method="GET",
                path="/projects",
                response_type=dict[str, str],
            )
    finally:
        await client.aclose()

    assert "API token support is intended for /public routes" in str(exc_info.value)


@pytest.mark.asyncio
async def test_store_set_sends_raw_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/store"
        assert request.method == "POST"
        assert request.url.params["key"] == "sample-key"
        assert request.url.params["ttl"] == "15"
        assert request.content == b"hello from sdk"
        return httpx.Response(201, json={"status": "ok", "key": "sample-key"})

    client = await _build_async_client(handler)
    try:
        payload = await client.store.set(key="sample-key", ttl=15, value="hello from sdk")
    finally:
        await client.aclose()

    assert payload["status"] == "ok"
    assert payload["key"] == "sample-key"


@pytest.mark.asyncio
async def test_storage_download_file_returns_binary_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/storage/download/file"
        assert request.url.params["connection_id"] == "conn-1"
        assert request.url.params["filename"] == "report.txt"
        return httpx.Response(
            200,
            content=b"payload-bytes",
            headers={
                "content-type": "text/plain",
                "content-disposition": 'attachment; filename="report.txt"',
            },
        )

    client = await _build_async_client(handler)
    try:
        payload = await client.storage.download.file(
            connection_id="conn-1",
            filename="report.txt",
            path="/tmp",
        )
    finally:
        await client.aclose()

    assert payload.content == b"payload-bytes"
    assert payload.content_type == "text/plain"
    assert payload.filename == "report.txt"


@pytest.mark.asyncio
async def test_auth_admin_users_delete_uses_nested_resource_path() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/auth/admin/users/user-1"
        assert request.method == "DELETE"
        return httpx.Response(200, json={"success": True, "message": "ok"})

    client = await _build_async_client(handler)
    try:
        response = await client.auth.admin.users.delete(user_identifier="user-1")
    finally:
        await client.aclose()

    assert response.success is True


def test_clients_expose_nested_resource_surface() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"alpha": "beta"})

    client = _build_sync_client(handler)
    try:
        assert hasattr(client.storage, "download")
        assert hasattr(client.storage.download, "file")
        assert hasattr(client.projects, "tasks")
        assert hasattr(client.projects.tasks, "new")
        assert hasattr(client.auth.admin, "users")
        assert not hasattr(client.storage, "download_file")
    finally:
        client.close()


def test_sync_client_exposes_resource_surface() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/store"
        return httpx.Response(200, json={"alpha": "beta"})

    client = _build_sync_client(handler)
    try:
        payload = client.store.list()
    finally:
        client.close()

    assert payload == {"alpha": "beta"}


def test_ddl_sdk_models_use_top_level_connection_id() -> None:
    request_models = (
        CreateDatabaseRequest,
        CreateSchemaRequest,
        CreateTableFromSQLRequest,
        CreateTableFromSchemaRequest,
        GenerateSchemaDDLRequest,
        GenerateTableDDL,
    )

    for model in request_models:
        assert "connection_id" in model.model_fields
        assert "connection_metadata" not in model.model_fields
        assert "connection_url" not in model.model_fields
