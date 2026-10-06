from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from services.gateway.routes.internal.ai_mcp import ddl_columns as ddl
from services.gateway.routes.internal.ai_mcp.errors import AIMCPHTTPError

from src.schemas.http.create_table import (
    ApplyTableColumnActionsResponse,
    ResolveWriteColumnsResponse,
)


@pytest.fixture
def context(monkeypatch):
    principal = SimpleNamespace(user=object())
    access = AsyncMock(return_value=SimpleNamespace(kind="sql"))
    resolve = AsyncMock(return_value=SimpleNamespace(
        connection_id="allowed", connection_string="postgresql://user:secret@host/db",
    ))
    invalidate = AsyncMock()
    monkeypatch.setattr(ddl, "get_accessible_connection", access)
    monkeypatch.setattr(ddl, "resolve_ddl_connection", resolve)
    monkeypatch.setattr(ddl, "invalidate_ddl_catalog", invalidate)
    return principal, access, resolve, invalidate


def action():
    return {"type": "set_column_comment", "column_name": "value", "comment": None}


@pytest.mark.asyncio
@pytest.mark.parametrize("preview", [None, True, False])
async def test_preview_and_apply_have_distinct_effects(context, monkeypatch, preview):
    principal, _, _, invalidate = context
    requests = []

    def operation(request, connection_string):
        requests.append(request)
        return ApplyTableColumnActionsResponse(message="done")

    monkeypatch.setattr(ddl, "apply_table_column_actions_from_connection_string", operation)
    kwargs = {} if preview is None else {"dry_run": preview}
    result = await ddl.apply_table_column_actions(
        principal=principal, redis="cache", connection_id="allowed", table_name="target",
        actions=[action()], **kwargs,
    )
    assert result["success"]
    request = requests[0]
    assert request.dry_run is (preview is not False)
    assert request.actions[0].comment is None
    assert "comment" in request.actions[0].model_fields_set
    assert "column" not in request.actions[0].model_fields_set
    if preview is False:
        invalidate.assert_awaited_once()
    else:
        invalidate.assert_not_awaited()


@pytest.mark.asyncio
async def test_partial_failure_invalidates_catalog_and_redacts_driver_error(context, monkeypatch):
    principal, _, _, invalidate = context
    operation = Mock(side_effect=RuntimeError("driver postgresql://user:secret@host/db"))
    monkeypatch.setattr(ddl, "apply_table_column_actions_from_connection_string", operation)
    with pytest.raises(AIMCPHTTPError) as raised:
        await ddl.apply_table_column_actions(
            principal=principal, redis="cache", connection_id="allowed", table_name="target",
            actions=[action()], dry_run=False,
        )
    invalidate.assert_awaited_once()
    assert raised.value.detail["code"] == "DDL_OPERATION_FAILED"
    assert "secret" not in str(raised.value.detail)


@pytest.mark.asyncio
async def test_resolution_is_read_only(context, monkeypatch):
    principal, _, _, invalidate = context
    operation = AsyncMock(return_value=ResolveWriteColumnsResponse())
    monkeypatch.setattr(ddl, "resolve_write_columns_from_connection_string", operation)
    await ddl.resolve_write_columns(
        principal=principal, connection_id="allowed", table_name="target",
        mode="typed_create", dataframe_metadata={"columns": [{"name": "id", "dtype": "INT"}]},
    )
    invalidate.assert_not_awaited()
    assert operation.await_args.args[0].mode == "typed_create"


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", ["resolve_write_columns", "apply_table_column_actions"])
@pytest.mark.parametrize("denial", ["scope", "non_sql"])
async def test_access_is_checked_before_credentials_or_db(context, monkeypatch, tool, denial):
    principal, access, resolve, invalidate = context
    if denial == "scope":
        access.side_effect = AIMCPHTTPError(403, "SCOPE_DENIED", "denied")
    else:
        access.return_value.kind = "file"
    kwargs = (
        {"actions": [action()], "redis": "cache"} if tool == "apply_table_column_actions"
        else {"mode": "existing_table", "dataframe_metadata": {"columns": []}}
    )
    with pytest.raises(AIMCPHTTPError):
        await getattr(ddl, tool)(
            principal=principal, connection_id="denied", table_name="target",
            **kwargs,
        )
    resolve.assert_not_awaited()
    invalidate.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("arguments", [
    {"actions": []},
    {"actions": [{"type": "set_column_comment", "column_name": "value"}]},
    {"actions": [action()], "dry_run": "false"},
    {"actions": [action()], "sql": "DROP TABLE target"},
    {"actions": [{"type": "set_column_nullable", "column_name": "value", "nullable": False,
                  "comment": None}]},
])
async def test_invalid_arguments_are_structured_and_have_no_side_effects(context, arguments):
    principal, access, resolve, invalidate = context
    with pytest.raises(AIMCPHTTPError) as raised:
        await ddl.apply_table_column_actions(
            principal=principal, redis="cache", connection_id="allowed", table_name="target",
            **arguments,
        )
    assert raised.value.detail["code"] == "INVALID_ARGUMENTS"
    access.assert_not_awaited()
    resolve.assert_not_awaited()
    invalidate.assert_not_awaited()


@pytest.mark.asyncio
async def test_unsupported_operation_is_structured(context, monkeypatch):
    principal, _, _, invalidate = context
    monkeypatch.setattr(
        ddl, "apply_table_column_actions_from_connection_string",
        Mock(side_effect=ValueError("operation not supported by driver")),
    )
    with pytest.raises(AIMCPHTTPError) as raised:
        await ddl.apply_table_column_actions(
            principal=principal, redis="cache", connection_id="allowed", table_name="target",
            actions=[action()],
        )
    assert raised.value.detail["code"] == "DDL_UNSUPPORTED"
    invalidate.assert_not_awaited()
