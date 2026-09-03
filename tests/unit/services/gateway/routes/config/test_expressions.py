from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from services.gateway.routes.config.router import router as config_router

from src.node_dsl.input_expressions.constants import (
    IMMUTABLE_INPUT_VARIABLES_SYSTEM_ATTRIBUTES_RULE,
)


@pytest.fixture
async def client():
    app = FastAPI()
    app.include_router(config_router, prefix="/api")

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as async_client:
        yield async_client


@pytest.mark.asyncio
async def test_get_expressions_config_returns_registered_environment_symbols(client):
    response = await client.get("/api/config/expressions")

    assert response.status_code == 200
    payload = response.json()

    assert payload["filters"]
    assert payload["tests"]
    assert payload["globals"]

    filter_names = {item["name"] for item in payload["filters"]}
    test_names = {item["name"] for item in payload["tests"]}
    global_names = {item["name"] for item in payload["globals"]}

    assert {"lower", "tojson"}.issubset(filter_names)
    assert "odd" in test_names
    assert {"len", "now"}.issubset(global_names)


@pytest.mark.asyncio
async def test_get_expressions_config_returns_default_policy_metadata(client):
    response = await client.get("/api/config/expressions")

    assert response.status_code == 200
    payload = response.json()
    default_policy = payload["default_policy"]

    assert default_policy["name"] == "default"
    assert "lower" in default_policy["allowed_filters"]
    assert "odd" in default_policy["allowed_tests"]
    assert "len" in default_policy["allowed_globals"]
    assert default_policy["allowed_attribute_rules"] == [
        IMMUTABLE_INPUT_VARIABLES_SYSTEM_ATTRIBUTES_RULE
    ]
    assert default_policy["allow_statements"] is False


@pytest.mark.asyncio
async def test_get_expressions_config_is_available_via_main_gateway_router(
    gateway_client,
    router_prefix,
):
    response = await gateway_client.get(f"{router_prefix}/config/expressions")

    assert response.status_code == 200
