from __future__ import annotations

import json
import os
from importlib.metadata import version
from unittest.mock import AsyncMock

import httpx
import pytest

pytest.importorskip("mcp")
# MCP 2.x does not expose __version__; use distribution metadata instead.
if int(version("mcp").split(".", 1)[0]) < 2:
    pytest.skip("dvt_ai_mcp server tests require MCP 2.x", allow_module_level=True)

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
    INSTRUCTIONS,
    _call,
    app,
    gateway_client,
    mcp,
    streamable_http_app,
)

EXPECTED_TOOLS = {
    "create_project",
    "list_project_schedules",
    "get_project_schedule",
    "set_project_schedule",
    "update_project_schedule",
    "set_project_schedule_enabled",
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
    "resolve_write_columns",
    "apply_table_column_actions",
    "list_storage",
    "preview_storage_file",
    "run_project",
    "get_task",
    "wait_task",
    "get_task_logs",
    "cancel_task",
}


def test_mcp_contract_exposes_supported_tools_with_annotations() -> None:
    tools = mcp._tool_manager.list_tools()
    assert {tool.name for tool in tools} == EXPECTED_TOOLS
    by_name = {tool.name: tool for tool in tools}
    assert by_name["list_projects"].annotations.read_only_hint is True
    assert by_name["apply_graph_changes"].annotations.destructive_hint is True
    assert by_name["run_project"].annotations.read_only_hint is False
    assert by_name["create_table"].annotations.idempotent_hint is True
    assert by_name["resolve_write_columns"].annotations.read_only_hint is True
    assert by_name["apply_table_column_actions"].annotations.destructive_hint is True
    assert by_name["apply_table_column_actions"].annotations.idempotent_hint is False
    assert by_name["create_project"].annotations.idempotent_hint is False
    assert by_name["create_project"].annotations.destructive_hint is False
    for name in ("list_project_schedules", "get_project_schedule"):
        assert by_name[name].annotations.read_only_hint is True
    for name in (
        "set_project_schedule", "update_project_schedule", "set_project_schedule_enabled",
    ):
        assert by_name[name].annotations.read_only_hint is False
        assert by_name[name].annotations.open_world_hint is True
    assert "never claim success before SUCCESS" in mcp.instructions
    assert "Never add or replace a node with a deprecated node type" in mcp.instructions
    assert "agent_description" in mcp.instructions
    assert "optional input can still require an explicit decision" in mcp.instructions
    assert "Never put a connection ID string or connection_ref directly" in mcp.instructions
    for node_name in (
        "ReadTableFromDBV3", "ReadQueryFromDBV3", "WriteDataFrameToDBV4",
        "GetExistDBConnection", "ExecutePython", "DataFrameExecCode", "ExecuteSQL",
    ):
        assert node_name not in mcp.instructions
    assert "Use search_nodes to find suitable node types" in mcp.instructions
    assert "read get_node_definition with the user's locale" in mcp.instructions
    assert "when parameters or errors are unclear" in mcp.instructions


@pytest.mark.asyncio
async def test_mcp_protocol_lists_all_tools() -> None:
    async with Client(mcp) as client:
        result = await client.list_tools()
    assert {tool.name for tool in result.tools} == EXPECTED_TOOLS
    by_name = {tool.name: tool for tool in result.tools}
    assert "mode" not in by_name["set_project_schedule"].input_schema["properties"]
    patch_schema = by_name["update_project_schedule"].input_schema
    assert "mode" not in patch_schema["$defs"]["SchedulePatch"]["properties"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("locale", "documentation"),
    [("en", "# DataFrame Join"), ("ru", "# Объединение DataFrame"), ("ru", None)],
)
async def test_mcp_protocol_forwards_definition_locale_and_documentation(
    monkeypatch, locale, documentation,
) -> None:
    payload = {
        "name": "DataFrameJoin", "documentation": documentation,
        "input_definitions": {
            "left_on": {
                "description": "Left key columns.",
                "agent_description": "Inspect key cardinality before joining.",
            },
        },
    }
    call = AsyncMock(return_value=payload)
    monkeypatch.setattr(gateway_client, "call_tool", call)

    async with Client(mcp) as client:
        result = await client.call_tool(
            "get_node_definition", {"node_name": "DataFrameJoin", "locale": locale},
        )

    call.assert_awaited_once_with(
        "get_node_definition", {"node_name": "DataFrameJoin", "locale": locale},
    )
    assert not result.is_error
    assert json.loads(result.content[0].text) == payload


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


def test_catalog_tools_explain_source_comments():
    by_name = {tool.name: tool for tool in mcp._tool_manager.list_tools()}
    assert "comments" in by_name["browse_database"].description
    assert "table/column comments" in by_name["get_database_table"].description.lower()
    assert "Comments are source documentation, not" in INSTRUCTIONS


@pytest.mark.asyncio
@pytest.mark.parametrize("tool,arguments", [
    ("create_project", {"name": "New project", "folder_id": "folder"}),
    ("list_project_schedules", {"cursor": None, "limit": 5}),
    ("get_project_schedule", {"project_id": "p"}),
    ("update_project_schedule", {
        "project_id": "p", "patch": {"force_exec": False, "max_retries": 0},
    }),
    ("set_project_schedule_enabled", {"project_id": "p", "enabled": False}),
    ("set_project_schedule", {
        "project_id": "p", "cron": "0 4 * * *",
        "force_exec": False, "max_retries": 0, "retry_delay_seconds": 60,
        "retry_backoff": "fixed", "retry_max_delay_seconds": 3600,
    }),
])
async def test_project_and_schedule_tools_forward_arguments(monkeypatch, tool, arguments):
    call = AsyncMock(return_value={"success": True})
    monkeypatch.setattr(gateway_client, "call_tool", call)
    async with Client(mcp) as client:
        result = await client.call_tool(tool, arguments)
    assert not result.is_error
    call.assert_awaited_once_with(tool, {
        key: value for key, value in arguments.items() if value is not None
    })


@pytest.mark.asyncio
@pytest.mark.parametrize("patch", [
    {}, {"max_retries": None}, {"max_retries": 11}, {"disabled": False},
    {"scheduled_by_user_id": "other"}, {"mode": "invalid"},
    {"mode": "metadata_only"}, {"mode": "full"},
])
async def test_schedule_patch_schema_rejects_invalid_fields(monkeypatch, patch):
    call = AsyncMock()
    monkeypatch.setattr(gateway_client, "call_tool", call)
    async with Client(mcp) as client:
        result = await client.call_tool(
            "update_project_schedule", {"project_id": "p", "patch": patch},
        )
    assert result.is_error
    call.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("status,code", [
    (404, "SCHEDULE_NOT_FOUND"),
    (422, "INVALID_ARGUMENTS"),
    (503, "SCHEDULER_UNAVAILABLE"),
    (404, "FOLDER_NOT_FOUND_OR_DENIED"),
])
async def test_new_gateway_errors_survive_http_adapter(monkeypatch, status, code):
    from services.dvt_ai_mcp.gateway_client import bearer_token_context

    detail = {"code": code, "message": "Safe operation error."}
    transport = httpx.MockTransport(
        lambda request: httpx.Response(status, json={"detail": detail}),
    )
    async with httpx.AsyncClient(transport=transport, base_url="http://gateway.test") as http:
        monkeypatch.setattr(gateway_client, "_client", http)
        context_token = bearer_token_context.set("test-token")
        try:
            with pytest.raises(MCPError) as error:
                await _call("get_project_schedule", {"project_id": "p"})
        finally:
            bearer_token_context.reset(context_token)
    assert error.value.data == {"dvt_error": detail}


@pytest.mark.asyncio
async def test_unknown_gateway_error_remains_redacted(monkeypatch):
    from services.dvt_ai_mcp.gateway_client import bearer_token_context

    transport = httpx.MockTransport(lambda request: httpx.Response(500, json={
        "detail": {"code": "UNKNOWN_INTERNAL", "message": "private backend details"},
    }))
    async with httpx.AsyncClient(transport=transport, base_url="http://gateway.test") as http:
        monkeypatch.setattr(gateway_client, "_client", http)
        context_token = bearer_token_context.set("test-token")
        try:
            with pytest.raises(MCPError) as error:
                await _call("get_project_schedule", {"project_id": "p"})
        finally:
            bearer_token_context.reset(context_token)
    assert error.value.data == {"dvt_error": {
        "code": "GATEWAY_UNAVAILABLE", "message": "Gateway operation failed.",
    }}


@pytest.mark.asyncio
async def test_column_actions_default_to_preview_and_preserve_explicit_null(monkeypatch):
    from services.dvt_ai_mcp.gateway_client import _jsonable

    captured = []

    async def call(name, arguments):
        captured.append((name, _jsonable(arguments)))
        return {"success": True}

    monkeypatch.setattr(gateway_client, "call_tool", call)
    async with Client(mcp) as client:
        for action in [
            {"type": "set_column_comment", "column_name": "value", "comment": None},
            {"type": "set_column_nullable", "column_name": "value", "nullable": False},
        ]:
            result = await client.call_tool("apply_table_column_actions", {
                "connection_id": "allowed", "table_name": "target", "actions": [action],
            })
            assert not result.is_error
    assert captured[0][1]["dry_run"] is True
    assert captured[0][1]["actions"][0] == {
        "type": "set_column_comment", "column_name": "value", "comment": None,
    }
    assert captured[1][1]["actions"][0] == {
        "type": "set_column_nullable", "column_name": "value", "nullable": False,
    }


@pytest.mark.asyncio
async def test_resolve_columns_forwards_metadata_mapping_and_returns_diagnostics(monkeypatch):
    from services.dvt_ai_mcp.gateway_client import _jsonable

    response = {"columns": [{"status": "missing_in_db"}], "diagnostics": []}
    captured = {}

    async def call(name, arguments):
        captured.update(_jsonable(arguments))
        return response

    monkeypatch.setattr(gateway_client, "call_tool", call)
    async with Client(mcp) as client:
        result = await client.call_tool("resolve_write_columns", {
            "connection_id": "allowed", "table_name": "target", "mode": "existing_table",
            "dataframe_metadata": {"columns": [
                {"name": "source", "dtype": "STRING", "nullable": True,
                 "dtype_metadata": {"name": "string", "class": "StringDtype", "origin": "pandas"}},
            ]},
            "column_mapping": [{"source_name": "source", "target_name": "target"}],
        })
    assert not result.is_error
    assert json.loads(result.content[0].text) == response
    assert captured["dataframe_metadata"]["columns"][0]["dtype_metadata"] == {
        "name": "string", "class_name": "StringDtype", "origin": "pandas",
    }
    assert captured["column_mapping"] == [{"source_name": "source", "target_name": "target"}]


@pytest.mark.asyncio
@pytest.mark.parametrize("action", [
    {"type": "set_column_comment", "column_name": "value"},
    {"type": "set_column_nullable", "column_name": "value", "nullable": "false"},
    {"type": "add_column", "column_name": "value"},
    {"type": "execute_sql", "column_name": "value", "sql": "DROP TABLE target"},
])
async def test_column_action_invalid_contract_cannot_reach_gateway(monkeypatch, action):
    call = AsyncMock()
    monkeypatch.setattr(gateway_client, "call_tool", call)
    async with Client(mcp) as client:
        result = await client.call_tool("apply_table_column_actions", {
            "connection_id": "allowed", "table_name": "target", "actions": [action],
        })
    assert result.is_error
    call.assert_not_awaited()
