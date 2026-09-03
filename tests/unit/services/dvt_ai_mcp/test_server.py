from __future__ import annotations

import os
from unittest.mock import AsyncMock

import httpx
import pytest

pytest.importorskip(
    "mcp",
    minversion="2.0.0",
    reason="dvt_ai_mcp server tests require the service-specific MCP 2.x environment",
)

from mcp import Client
from mcp.shared.exceptions import MCPError

os.environ.setdefault("DVT_ENVIRONMENT", "dev")
os.environ.setdefault("DVT_PUBLIC_URL", "http://localhost")
os.environ.setdefault(
    "DVT_AI_MCP_INTERNAL_SECRET",
    "dev-ai-mcp-internal-secret-change-me",
)

from services.dvt_ai_mcp.gateway_client import GatewayToolError
from services.dvt_ai_mcp.server import (
    _call,
    app,
    gateway_client,
    mcp,
    streamable_http_app,
)

EXPECTED_TOOLS = {
    "list_projects",
    "get_project",
    "get_project_graph",
    "search_nodes",
    "get_node_definition",
    "validate_graph_changes",
    "apply_graph_changes",
    "list_connections",
    "get_connection",
    "browse_database",
    "get_database_table",
    "query_database_readonly",
    "create_database",
    "create_schema",
    "create_table",
    "list_storage",
    "preview_storage_file",
    "run_project",
    "get_task",
    "wait_task",
    "get_task_logs",
    "cancel_task",
}


def test_mcp_contract_exposes_only_mvp_tools_with_annotations() -> None:
    tools = mcp._tool_manager.list_tools()
    assert {tool.name for tool in tools} == EXPECTED_TOOLS
    by_name = {tool.name: tool for tool in tools}
    assert by_name["list_projects"].annotations.read_only_hint is True
    assert by_name["apply_graph_changes"].annotations.destructive_hint is True
    assert by_name["run_project"].annotations.read_only_hint is False
    assert by_name["create_table"].annotations.idempotent_hint is True
    assert "never claim success before SUCCESS" in mcp.instructions
    assert "Never add or replace a node with a deprecated node type" in mcp.instructions
    assert "For an ordinary database table read, use ReadTableFromDBV3" in mcp.instructions
    assert "partition_col to an exact raw catalog column name" in mcp.instructions
    assert "pass every catalog column" in mcp.instructions
    assert "WriteDataFrameToDBV4 never creates" in mcp.instructions
    assert "Never put a connection ID string or connection_ref directly" in mcp.instructions
    assert "GetExistDBConnection" in mcp.instructions


@pytest.mark.asyncio
async def test_mcp_protocol_lists_all_tools() -> None:
    async with Client(mcp) as client:
        result = await client.list_tools()
    assert {tool.name for tool in result.tools} == EXPECTED_TOOLS


@pytest.mark.asyncio
async def test_gateway_error_is_exposed_as_structured_mcp_error(monkeypatch) -> None:
    monkeypatch.setattr(
        gateway_client,
        "call_tool",
        AsyncMock(
            side_effect=GatewayToolError(
                "SCOPE_DENIED",
                "Resource is unavailable.",
                {"resource": "project"},
            )
        ),
    )

    with pytest.raises(MCPError) as raised:
        await _call("get_project", {"project_id": "project-id"})

    assert raised.value.data == {
        "dvt_error": {
            "code": "SCOPE_DENIED",
            "message": "Resource is unavailable.",
            "details": {"resource": "project"},
        }
    }


@pytest.mark.asyncio
async def test_health_is_public_and_mcp_requires_bearer() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://localhost",
    ) as client:
        health = await client.get("/health")
        denied = await client.post("/mcp", json={})

    assert health.status_code == 200
    assert health.json()["service"] == "dvt_ai_mcp"
    assert denied.status_code == 401
    assert denied.json()["error"]["code"] == "AUTH_INVALID"


@pytest.mark.asyncio
async def test_transport_rejects_invalid_host_and_origin(monkeypatch) -> None:
    monkeypatch.setattr(gateway_client, "verify", AsyncMock(return_value={"valid": True}))
    headers = {"Authorization": "Bearer test", "Host": "evil.example"}
    async with (
        streamable_http_app.router.lifespan_context(streamable_http_app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://localhost",
        ) as client,
    ):
        invalid_host = await client.post("/mcp", headers=headers, json={})
        invalid_origin = await client.post(
            "/mcp",
            headers={
                "Authorization": "Bearer test",
                "Host": "localhost",
                "Origin": "https://evil.example",
            },
            json={},
        )

    assert invalid_host.status_code == 421
    assert invalid_origin.status_code == 403
