from __future__ import annotations

from typing import Any, AsyncGenerator

import httpx
import pytest

from .settings import IntegrationTestSettings


def _build_setup_payload(
    step: dict[str, Any],
    settings: IntegrationTestSettings,
) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for field in step.get("fields", []):
        key = field["key"]
        field_type = field.get("type")
        current_value = field.get("value")
        if current_value not in {None, ""}:
            values[key] = current_value
            continue
        if key == "name":
            values[key] = settings.default_organization_name
        elif key == "email":
            values[key] = settings.default_email
        elif key == "password":
            values[key] = settings.default_password
        elif key == "license.key":
            values[key] = settings.default_license_key
        elif field_type == "boolean":
            values[key] = True
        elif field_type == "number":
            values[key] = 1
        else:
            values[key] = f"e2e-{key}"
    return values


def _ensure_gateway_setup(
    gateway_base_url: str,
    settings: IntegrationTestSettings,
) -> tuple[str, str]:
    with httpx.Client(base_url=gateway_base_url, timeout=30.0) as client:
        for _ in range(20):
            setup_status = client.get("/api/setup/status")
            setup_status.raise_for_status()
            status_body = setup_status.json()

            if status_body.get("initialized", False):
                return settings.default_email, settings.default_password

            next_step = next(
                (step for step in status_body.get("steps", []) if not step.get("completed", False)),
                None,
            )
            if next_step is None:
                raise RuntimeError(
                    "Gateway setup is not initialized but no incomplete setup step was returned."
                )

            setup_response = client.post(
                f"/api/setup/{next_step['code']}",
                json={"values": _build_setup_payload(next_step, settings)},
            )
            if setup_response.status_code not in {200, 409}:
                setup_response.raise_for_status()

        raise RuntimeError("Gateway setup did not complete after 20 attempts.")


@pytest.fixture(scope="session")
def gateway_live_base_url(gateway_container) -> str:
    host = gateway_container.get_container_host_ip()
    port = gateway_container.get_exposed_port(8000)
    return f"http://{host}:{port}"


@pytest.fixture(scope="session")
def gateway_setup_credentials(
    gateway_live_base_url: str,
    integration_test_settings: IntegrationTestSettings,
) -> tuple[str, str]:
    return _ensure_gateway_setup(gateway_live_base_url, integration_test_settings)


@pytest.fixture(scope="session")
def gateway_auth_headers(
    gateway_live_base_url: str,
    gateway_setup_credentials: tuple[str, str],
) -> dict[str, str]:
    email, password = gateway_setup_credentials

    with httpx.Client(base_url=gateway_live_base_url, timeout=30.0) as client:
        login_response = client.post(
            "/api/auth/sign-in",
            json={
                "auth_provider": "email",
                "email": email,
                "password": password,
            },
        )
        login_response.raise_for_status()

        token_response = client.post(
            "/api/auth/api-tokens",
            json={
                "name": "integration-api-key",
                "expires_at": None,
                "whitelisted_ip_addresses": None,
                "description": "integration tests",
            },
        )
        token_response.raise_for_status()

        payload = token_response.json()
        token = payload.get("data", {}).get("token")
        if not token:
            raise RuntimeError(f"Bad API key response: {payload}")

        return {"X-API-Key": token}


@pytest.fixture
async def gateway_live_client(
    gateway_live_base_url: str,
    gateway_auth_headers: dict[str, str],
) -> AsyncGenerator[httpx.AsyncClient, None]:
    async with httpx.AsyncClient(base_url=gateway_live_base_url, timeout=30.0) as client:
        client.headers.update(gateway_auth_headers)
        yield client


@pytest.fixture
async def gateway_live_unauthenticated_client(
    gateway_live_base_url: str,
) -> AsyncGenerator[httpx.AsyncClient, None]:
    async with httpx.AsyncClient(base_url=gateway_live_base_url, timeout=30.0) as client:
        yield client
