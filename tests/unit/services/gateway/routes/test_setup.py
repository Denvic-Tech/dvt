from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from services.gateway.routes import setup as setup_route
from src.db import get_async_session
from src.setup import SetupConflictError, SetupValidationError
from src.setup.dsl import SetupStatus, SetupStep, SetupStepField


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
