from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from services.gateway.routes.internal.ai_mcp import schedules
from services.gateway.routes.internal.ai_mcp.errors import AIMCPHTTPError, denied
from services.gateway.routes.internal.ai_mcp.router import call_tool
from services.gateway.routes.internal.ai_mcp.schemas import ToolCallSchema

from src.modules.project.infra.http_schemas import ScheduleResponse
from src.pipeline.execution_mode import PipelineExecutionMode
from src.schemas.internal.project_scheduler import ProjectScheduleResponse


@pytest.fixture
def setup(monkeypatch):
    principal = SimpleNamespace(
        user=SimpleNamespace(id="admin", role="admin", organization_id="org"),
        token=SimpleNamespace(id="token"),
    )
    current = ProjectScheduleResponse(
        project_id="p", cron="15 2 * * *", force_exec=True, max_retries=3,
    )
    client = SimpleNamespace(
        get_scheduled_projects=AsyncMock(return_value=[current]),
        schedule_project=AsyncMock(return_value=ScheduleResponse(
            success=True, message="saved", project_id="p",
        )),
        patch_project_schedule=AsyncMock(return_value=ScheduleResponse(
            success=True, message="updated", project_id="p",
        )),
    )
    context = AsyncMock()
    context.__aenter__.return_value = client
    monkeypatch.setattr(schedules, "SchedulerClient", lambda: context)
    accessible = AsyncMock(return_value=SimpleNamespace(id="p"))
    connections = AsyncMock()
    history = AsyncMock(return_value={})
    monkeypatch.setattr(schedules, "get_accessible_project", accessible)
    monkeypatch.setattr(schedules, "_check_execution_connections", connections)
    monkeypatch.setattr(schedules, "get_recent_scheduler_runs_by_project_ids", history)
    monkeypatch.setattr(
        schedules, "list_accessible_projects", AsyncMock(return_value=[SimpleNamespace(id="p")]),
    )
    return SimpleNamespace(
        principal=principal, session=AsyncMock(), client=client, current=current,
        connections=connections, accessible=accessible, history=history,
    )


async def invoke(setup, tool, **arguments):
    return (await call_tool(
        tool, ToolCallSchema(arguments=arguments), setup.session, setup.principal, None, None,
    )).result


@pytest.mark.asyncio
@pytest.mark.parametrize("tool,arguments", [
    ("list_project_schedules", {}),
    ("get_project_schedule", {"project_id": "p"}),
    ("set_project_schedule", {"project_id": "p", "cron": "0 * * * *"}),
    ("update_project_schedule", {"project_id": "p", "patch": {"max_retries": 0}}),
    ("set_project_schedule_enabled", {"project_id": "p", "enabled": False}),
])
async def test_non_admin_cannot_use_schedules(setup, tool, arguments):
    setup.principal.user.role = "user"
    with pytest.raises(AIMCPHTTPError) as error:
        await invoke(setup, tool, **arguments)
    assert error.value.detail["code"] == "SCOPE_DENIED"
    setup.client.get_scheduled_projects.assert_not_awaited()
    setup.client.schedule_project.assert_not_awaited()
    setup.client.patch_project_schedule.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("tool,arguments", [
    ("get_project_schedule", {}),
    ("set_project_schedule", {"cron": "0 * * * *"}),
    ("update_project_schedule", {"patch": {"max_retries": 0}}),
    ("set_project_schedule_enabled", {"enabled": False}),
])
async def test_denied_project_never_reaches_scheduler(setup, tool, arguments):
    setup.accessible.side_effect = denied("project")
    with pytest.raises(AIMCPHTTPError) as error:
        await invoke(setup, tool, project_id="hidden", **arguments)
    assert error.value.detail["code"] == "PROJECT_NOT_FOUND_OR_DENIED"
    setup.client.get_scheduled_projects.assert_not_awaited()
    setup.client.schedule_project.assert_not_awaited()
    setup.client.patch_project_schedule.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("disabled", [True, False])
async def test_partial_update_preserves_omitted_settings_and_false_zero(setup, disabled):
    setup.current.mode = PipelineExecutionMode.METADATA_ONLY
    setup.current.disabled = disabled
    await invoke(
        setup, "update_project_schedule", project_id="p",
        patch={"force_exec": False, "max_retries": 0},
    )
    setup.client.patch_project_schedule.assert_awaited_once_with(
        project_id="p",
        data={
            "force_exec": False, "max_retries": 0, "mode": "full",
            "scheduled_by_user_id": "admin",
        },
    )
    assert setup.connections.await_count == int(not disabled)


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [True, False])
async def test_switch_enforces_full_on_enable_and_preserves_settings_on_disable(setup, enabled):
    setup.current.mode = PipelineExecutionMode.METADATA_ONLY
    setup.current.disabled = not enabled
    await invoke(setup, "set_project_schedule_enabled", project_id="p", enabled=enabled)
    setup.client.patch_project_schedule.assert_awaited_once_with(
        project_id="p", data={
            "disabled": not enabled, "scheduled_by_user_id": "admin",
            **({"mode": "full"} if enabled else {}),
        },
    )
    assert setup.connections.await_count == int(enabled)


@pytest.mark.asyncio
async def test_disabled_schedule_can_be_edited_without_connection_access(setup):
    setup.current.disabled = True
    setup.connections.side_effect = denied("connection")
    await invoke(setup, "update_project_schedule", project_id="p", patch={"cron": "0 3 * * *"})
    setup.connections.assert_not_awaited()
    assert "disabled" not in setup.client.patch_project_schedule.call_args.kwargs["data"]


@pytest.mark.asyncio
@pytest.mark.parametrize("tool,arguments", [
    ("set_project_schedule", {"cron": "0 * * * *"}),
    ("update_project_schedule", {"patch": {"max_retries": 0}}),
    ("set_project_schedule_enabled", {"enabled": True}),
])
async def test_activation_cannot_bypass_connection_scope(setup, tool, arguments):
    setup.connections.side_effect = denied("connection")
    with pytest.raises(AIMCPHTTPError) as error:
        await invoke(setup, tool, project_id="p", **arguments)
    assert error.value.detail["code"] == "CONNECTION_NOT_FOUND_OR_DENIED"
    setup.client.schedule_project.assert_not_awaited()
    setup.client.patch_project_schedule.assert_not_awaited()


@pytest.mark.asyncio
async def test_set_schedule_passes_defaults_and_authenticated_actor(setup):
    result = await invoke(setup, "set_project_schedule", project_id="p", cron="0 * * * *")
    assert result["success"] is True
    setup.client.schedule_project.assert_awaited_once_with(data={
        "project_id": "p", "cron": "0 * * * *", "mode": "full", "force_exec": False,
        "max_retries": 0, "retry_delay_seconds": 60, "retry_backoff": "fixed",
        "retry_max_delay_seconds": 3600, "scheduled_by_user_id": "admin",
    })


@pytest.mark.asyncio
@pytest.mark.parametrize("tool,arguments", [
    ("set_project_schedule", {"cron": "not cron"}),
    ("set_project_schedule", {"cron": "0 * * * *", "mode": "metadata_only"}),
    ("set_project_schedule", {"cron": "0 * * * *", "mode": "full"}),
    ("update_project_schedule", {"patch": {"mode": "metadata_only"}}),
    ("update_project_schedule", {"patch": {"mode": "full"}}),
    ("set_project_schedule", {"cron": "0 * * * *", "max_retries": 11}),
    ("set_project_schedule", {"cron": "0 * * * *", "scheduled_by_user_id": "other"}),
    ("update_project_schedule", {"patch": {"cron": "bad"}}),
    ("update_project_schedule", {"patch": {"max_retries": None}}),
    ("update_project_schedule", {"patch": {"disabled": True}}),
    ("update_project_schedule", {"patch": {"scheduled_by_user_id": "other"}}),
    ("update_project_schedule", {"patch": {}}),
    ("update_project_schedule", {"patch": {
        "retry_backoff": "exponential", "retry_delay_seconds": 4000,
    }}),
    ("set_project_schedule_enabled", {"enabled": "false"}),
    ("get_project_schedule", {"principal": {}}),
])
async def test_invalid_settings_are_structured_and_not_written(setup, tool, arguments):
    with pytest.raises(AIMCPHTTPError) as error:
        await invoke(setup, tool, project_id="p", **arguments)
    assert error.value.detail["code"] == "INVALID_ARGUMENTS"
    setup.client.schedule_project.assert_not_awaited()
    setup.client.patch_project_schedule.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_schedule_read_and_mutations(setup):
    setup.client.get_scheduled_projects.return_value = []
    assert await invoke(setup, "get_project_schedule", project_id="p") == {"schedule": None}
    for tool, arguments in [
        ("update_project_schedule", {"patch": {"max_retries": 0}}),
        ("set_project_schedule_enabled", {"enabled": False}),
    ]:
        with pytest.raises(AIMCPHTTPError) as error:
            await invoke(setup, tool, project_id="p", **arguments)
        assert error.value.detail["code"] == "SCHEDULE_NOT_FOUND"


@pytest.mark.asyncio
async def test_filter_before_pagination_and_history(setup, monkeypatch):
    setup.current.disabled = True
    second = ProjectScheduleResponse(project_id="q", cron="0 * * * *")
    hidden = ProjectScheduleResponse(project_id="a-hidden", cron="0 * * * *")
    setup.client.get_scheduled_projects.return_value = [hidden, second, setup.current]
    monkeypatch.setattr(schedules, "list_accessible_projects", AsyncMock(
        return_value=[SimpleNamespace(id="p"), SimpleNamespace(id="q")],
    ))
    page = await invoke(setup, "list_project_schedules", limit=1)
    assert [item["project_id"] for item in page["items"]] == ["p"]
    assert page["items"][0]["disabled"] is True
    assert "mode" not in page["items"][0]
    current = await invoke(setup, "get_project_schedule", project_id="p")
    assert "mode" not in current["schedule"]
    assert setup.history.call_args.kwargs["project_ids"] == ["p"]
    page = await invoke(setup, "list_project_schedules", limit=1, cursor=page["next_cursor"])
    assert [item["project_id"] for item in page["items"]] == ["q"]
    assert page["next_cursor"] is None
    assert setup.history.call_args.kwargs["project_ids"] == ["q"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status,code", [
    (404, "SCHEDULE_NOT_FOUND"), (422, "INVALID_ARGUMENTS"), (503, "SCHEDULER_UNAVAILABLE"),
    (500, "SCHEDULER_UNAVAILABLE"),
])
async def test_scheduler_errors_are_safe(setup, status, code):
    setup.client.get_scheduled_projects.side_effect = HTTPException(
        status, "http://private-scheduler:8000 secret=secret-value",
    )
    with pytest.raises(AIMCPHTTPError) as error:
        await invoke(setup, "get_project_schedule", project_id="p")
    assert error.value.detail["code"] == code
    assert "private-scheduler" not in str(error.value.detail)
    assert "secret-value" not in str(error.value.detail)
