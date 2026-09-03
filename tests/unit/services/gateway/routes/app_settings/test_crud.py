from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from services.gateway.routes.app_settings.main_router import router as app_settings_router
from services.gateway.routes.app_settings.routes import crud as crud_module

from src.db import get_async_session
from src.modules.app_settings import DVTApplicationSettings
from src.modules.app_settings.domain.entities import SettingChange
from src.modules.user.infra.fastapi.dependencies import get_user_admin_access_only


def make_settings(overrides: dict[str, object] | None = None):
    return DVTApplicationSettings.build_runtime_model(
        DVTApplicationSettings.validate_values(
            {
                **DVTApplicationSettings.default_values(),
                **(overrides or {}),
            }
        )
    )


@pytest.fixture
def fake_session():
    class FakeSession:
        def __init__(self):
            self.commit = AsyncMock()
            self.refresh = AsyncMock()

    return FakeSession()


@pytest.fixture
async def client(fake_session):
    app = FastAPI()

    async def override_get_async_session():
        yield fake_session

    app.include_router(app_settings_router, prefix="/api")
    app.dependency_overrides[get_async_session] = override_get_async_session
    app.dependency_overrides[get_user_admin_access_only] = lambda: None

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as async_client:
        yield async_client


@pytest.mark.asyncio
async def test_get_app_settings_returns_model_payload(client, fake_session, monkeypatch):
    get_app_settings = AsyncMock(
        return_value=make_settings(
            {
                "dcc.url": "https://example.test",
                "dcc.username": "tester",
            }
        )
    )
    monkeypatch.setattr(crud_module.helpers, "get_app_settings", get_app_settings)

    response = await client.get("/api/app-settings")

    assert response.status_code == 200
    assert response.json()["dcc"]["url"] == "https://example.test"
    assert response.json()["dcc"]["username"] == "tester"
    assert get_app_settings.await_args.kwargs["session"] is fake_session


@pytest.mark.asyncio
async def test_upsert_app_settings_updates_values_and_persists(client, fake_session, monkeypatch):
    get_app_settings = AsyncMock(
        return_value=make_settings(
            {
                "dcc.url": "https://new.example.test",
                "dcc.username": "updated-user",
            }
        )
    )
    set_setting_value = AsyncMock()
    monkeypatch.setattr(crud_module.helpers, "get_app_settings", get_app_settings)
    monkeypatch.setattr(crud_module.helpers, "set_setting_value", set_setting_value)

    response = await client.post(
        "/api/app-settings",
        params={"validate": "true"},
        json={
            "dcc": {
                "url": "https://new.example.test",
                "username": "updated-user",
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["dcc"]["url"] == "https://new.example.test"
    assert response.json()["dcc"]["username"] == "updated-user"
    assert [call.args[:2] for call in set_setting_value.await_args_list] == [
        ("dcc.url", "https://new.example.test"),
        ("dcc.username", "updated-user"),
    ]
    fake_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_app_settings_by_key_returns_scalar_value(client, monkeypatch):
    monkeypatch.setattr(
        crud_module.helpers,
        "get_app_settings",
        AsyncMock(return_value=make_settings({"dcc.url": "https://example.test"})),
    )

    response = await client.get("/api/app-settings/dcc.url")

    assert response.status_code == 200
    assert response.json() == "https://example.test"


@pytest.mark.asyncio
async def test_get_app_settings_by_key_returns_404_for_unknown_key(client, monkeypatch):
    monkeypatch.setattr(
        crud_module.helpers,
        "get_app_settings",
        AsyncMock(return_value=make_settings()),
    )

    response = await client.get("/api/app-settings/missing.key")

    assert response.status_code == 404
    assert response.json()["detail"] == "App setting key not found"


@pytest.mark.asyncio
async def test_set_app_settings_value_updates_single_field_and_awaits_persist(
    client,
    fake_session,
    monkeypatch,
):
    set_setting_value = AsyncMock(return_value="https://new.example.test")
    monkeypatch.setattr(crud_module.helpers, "set_setting_value", set_setting_value)

    response = await client.post(
        "/api/app-settings/dcc.url",
        params={"validate": "true"},
        json="https://new.example.test",
    )

    assert response.status_code == 201
    assert response.json() == "https://new.example.test"
    assert set_setting_value.await_args.args[:2] == ("dcc.url", "https://new.example.test")
    fake_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_setting_history_returns_changes(client, monkeypatch):
    from datetime import UTC, datetime

    monkeypatch.setattr(
        crud_module.helpers,
        "get_setting_history",
        AsyncMock(
            return_value=[
                SettingChange(
                    key="dcc.url",
                    old_value=None,
                    new_value="https://example.test",
                    changed_at=datetime(2026, 7, 29, tzinfo=UTC),
                    changed_by="tester",
                )
            ]
        ),
    )

    response = await client.get("/api/app-settings/dcc.url/history")

    assert response.status_code == 200
    assert response.json()[0]["key"] == "dcc.url"
    assert response.json()[0]["new_value"] == "https://example.test"
