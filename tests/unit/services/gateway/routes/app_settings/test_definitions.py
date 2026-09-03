from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from services.gateway.routes.app_settings.main_router import router as app_settings_router

from src.modules.user.infra.fastapi.dependencies import get_user_admin_access_only


@pytest.fixture
async def client():
    app = FastAPI()
    app.include_router(app_settings_router, prefix="/api")
    app.dependency_overrides[get_user_admin_access_only] = lambda: None

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as async_client:
        yield async_client


@pytest.mark.asyncio
async def test_get_app_setting_definitions_returns_registry_metadata(client):
    response = await client.get("/api/app-settings/definitions")

    assert response.status_code == 200
    payload = {item["key"]: item for item in response.json()}

    assert "dcc.password" in payload
    dcc_password = payload["dcc.password"]
    assert dcc_password["namespace"] == "dcc"
    assert dcc_password["group"] is None
    assert dcc_password["name"] == "password"
    assert dcc_password["value_type"] == {"type": "string"}
    assert dcc_password["nullable"] is True
    assert dcc_password["required"] is False
    assert dcc_password["secret"] is True
    assert dcc_password["bootstrap"] is False
    assert dcc_password["read_env"] is False
    assert dcc_password["env_var"] is None
    assert dcc_password["setup_label"] == "DCC Password"
    assert dcc_password["setup_type"] == "password"
    assert "unfilled" not in dcc_password


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "/api/app-settings/fields/required",
        "/api/app-settings/fields/required/unfilled",
    ],
)
async def test_old_field_routes_are_removed(client, url):
    response = await client.get(url)

    assert response.status_code == 404
