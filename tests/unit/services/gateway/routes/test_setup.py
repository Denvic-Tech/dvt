from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from services.gateway.routes import setup as setup_route

from src.db import get_async_session
from src.setup import SetupConflictError, SetupValidationError
from src.setup.dsl import SetupStatus, SetupStep, SetupStepField
from src.setup.steps.superadmin import SuperadminSetupPayload, SuperadminSetupStep


@pytest.fixture
def fake_session():
    class FakeSession:
        pass

    return FakeSession()


@pytest.fixture
async def client(fake_session):
    app = FastAPI()

    async def override_get_async_session():
        yield fake_session

    app.include_router(setup_route.router, prefix="/api")
    app.dependency_overrides[get_async_session] = override_get_async_session

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as async_client:
        yield async_client


def make_status(initialized: bool) -> SetupStatus:
    return SetupStatus(
        initialized=initialized,
        steps=[
            SetupStep(
                code="organization",
                title="Organization",
                description="Create organization",
                submit_label="Save organization",
                completed=initialized,
                fields=[
                    SetupStepField(
                        key="name",
                        label="Organization Name",
                        type="text",
                        required=True,
                        nullable=False,
                    )
                ],
            ),
            SetupStep(
                code="superadmin",
                title="Superadmin",
                description="Create superadmin",
                submit_label="Create superadmin",
                completed=initialized,
                fields=[
                    SetupStepField(
                        key="email",
                        label="Email",
                        type="email",
                        required=True,
                        nullable=False,
                    ),
                    SetupStepField(
                        key="password",
                        label="Password",
                        type="password",
                        required=True,
                        nullable=False,
                    ),
                ],
            ),
            SetupStep(
                code="app_config",
                title="Application Configuration",
                description="Configure app",
                submit_label="Save configuration",
                completed=initialized,
                fields=[
                    SetupStepField(
                        key="license.key",
                        label="License Key",
                        type="text",
                        required=True,
                        nullable=False,
                    )
                ],
            ),
        ],
    )


@pytest.mark.asyncio
async def test_get_setup_status_returns_setup_payload(client, fake_session, monkeypatch):
    get_status = AsyncMock(return_value=make_status(initialized=False))
    monkeypatch.setattr(setup_route.setup, "get_setup_status", get_status)

    response = await client.get("/api/setup/status")

    assert response.status_code == 200
    assert response.json()["initialized"] is False
    assert get_status.await_args.args[0] is fake_session


def test_dynamic_setup_routes_are_registered():
    route_paths = {
        route.path
        for route in setup_route.router.routes
        if "POST" in getattr(route, "methods", set())
    }

    assert {"/setup/organization", "/setup/superadmin", "/setup/app_settings"} <= route_paths


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("step_code", "payload"),
    [
        ("organization", {"name": "Acme"}),
        ("superadmin", {"email": "admin@example.com", "password": "secret"}),
        ("app_settings", {"license.key": "license"}),
    ],
)
async def test_submit_setup_step_returns_updated_status(
    client,
    fake_session,
    monkeypatch,
    step_code: str,
    payload: dict[str, str],
):
    submit_step = AsyncMock(return_value=make_status(initialized=False))
    monkeypatch.setattr(setup_route.setup, "submit_setup_step", submit_step)

    response = await client.post(
        f"/api/setup/{step_code}",
        json={"values": payload},
    )

    assert response.status_code == 200
    assert submit_step.await_args.args[0] is fake_session
    assert submit_step.await_args.kwargs == {
        "step_code": step_code,
        "values": payload,
    }


@pytest.mark.asyncio
async def test_submit_setup_step_maps_conflict_error(client, monkeypatch):
    monkeypatch.setattr(
        setup_route.setup,
        "submit_setup_step",
        AsyncMock(side_effect=SetupConflictError("already configured")),
    )

    response = await client.post(
        "/api/setup/organization",
        json={"values": {"name": "Acme"}},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "already configured"


@pytest.mark.asyncio
async def test_submit_setup_step_maps_validation_error(client, monkeypatch):
    monkeypatch.setattr(
        setup_route.setup,
        "submit_setup_step",
        AsyncMock(side_effect=SetupValidationError("invalid payload")),
    )

    response = await client.post(
        "/api/setup/app_settings",
        json={"values": {"license.key": None}},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "invalid payload"


@pytest.mark.asyncio
async def test_enrolled_setup_does_not_disclose_steps_or_accept_unpaired_browser(
    client, fake_session, monkeypatch,
):
    operation_id = uuid4()
    origin = "http://testserver"
    fake_session.execute = AsyncMock()
    monkeypatch.setattr(setup_route, "manager_origin", lambda: "https://localhost:8888")
    monkeypatch.setattr(setup_route, "_deployment_id", lambda: operation_id)
    monkeypatch.setattr(setup_route, "_setup_cookie_mac", lambda *_: "recorded-signature")
    monkeypatch.setattr(setup_route.config.GATEWAY, "GATEWAY_ORIGINS", [origin])
    monkeypatch.setattr(setup_route.config.GATEWAY, "GATEWAY_COOKIE_SECURE", False)
    monkeypatch.setattr(setup_route.setup, "is_setup_initialized", AsyncMock(return_value=False))
    monkeypatch.setattr(setup_route.setup, "get_setup_status", AsyncMock(return_value=make_status(False)))
    deliver = AsyncMock()
    monkeypatch.setattr(setup_route, "operator_request", deliver)
    headers = {"Origin": origin, "X-DVT-CSRF": "1"}
    code = "p" * 43

    get_status = await client.get("/api/setup/status")
    assert get_status.json() == {"initialized": False, "pairing_required": True, "steps": []}
    assert (await client.post("/api/setup/superadmin", headers=headers, json={"values": {}})).status_code == 403
    assert (await client.post("/api/setup/pairing", json={
        "operation_id": str(operation_id), "code": code,
    })).status_code == 403
    assert (await client.post("/api/setup/pairing", headers=headers, json={
        "operation_id": str(uuid4()), "code": code,
    })).status_code == 409
    deliver.assert_not_called()

    paired = await client.post("/api/setup/pairing", headers=headers, json={
        "operation_id": str(operation_id), "code": code,
    })
    assert paired.status_code == 200
    assert all(flag in paired.headers["Set-Cookie"] for flag in ("HttpOnly", "SameSite=strict", "Path=/api/setup"))
    assert code not in paired.text and code not in paired.headers["Set-Cookie"]
    deliver.assert_awaited_once_with(
        "POST", f"/api/operator/setup/{operation_id}/exchange", json={"code": code},
    )
    assert len((await client.get("/api/setup/status")).json()["steps"]) == 3


@pytest.mark.asyncio
async def test_invalid_first_admin_email_is_a_field_error_without_password_echo(client, monkeypatch):
    def validate(_session, *, step_code, values):
        assert step_code == "superadmin"
        SuperadminSetupStep.validate_model(SuperadminSetupPayload, values)

    monkeypatch.setattr(setup_route.setup, "submit_setup_step", AsyncMock(side_effect=validate))
    response = await client.post("/api/setup/superadmin", json={
        "values": {"email": "invalid-email", "password": "do-not-echo-this"},
    })

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "values", "email"]
    assert "do-not-echo-this" not in response.text


@pytest.mark.asyncio
async def test_setup_status_retries_lost_completion_receipt(client, monkeypatch):
    operation_id = uuid4()
    monkeypatch.setattr(setup_route, "manager_origin", lambda: "https://localhost:8888")
    monkeypatch.setattr(
        setup_route.MigrationContext, "read",
        lambda: SimpleNamespace(operation_id=operation_id, source=None),
    )
    monkeypatch.setattr(
        setup_route.setup, "is_setup_initialized", AsyncMock(return_value=True),
    )
    notify = AsyncMock(side_effect=[HTTPException(503), None])
    monkeypatch.setattr(setup_route, "operator_request", notify)

    for _ in range(3):
        result = await client.get("/api/setup/status")
        assert result.json() == {"initialized": True, "pairing_required": False, "steps": []}
    assert notify.await_count == 2
    notify.assert_awaited_with(
        "POST", f"/api/operator/setup/{operation_id}/complete", timeout=5,
    )
