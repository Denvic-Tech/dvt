"""Dispatch behavior, independent of the actual tool's database/network work."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from services.gateway.routes.internal.ai_mcp.errors import AIMCPHTTPError
from services.gateway.routes.internal.ai_mcp.router import impl as handlers, registry
from services.gateway.routes.internal.ai_mcp.schemas import ToolCallSchema

from src.modules.db_catalog.domain import exceptions as catalog_errors
from src.modules.file_storage.domain.exceptions import FileStorageDomainError
from src.modules.file_storage.flow import exceptions as storage_errors

# Dependency and transaction contract before the router refactor.
DISPATCH_CASES = [
    ("list_projects", ("session",), False),
    ("get_project", ("session",), False),
    ("search_nodes", ("session",), False),
    ("get_node_definition", ("session",), False),
    ("create_project", ("session",), False),
    ("list_project_schedules", ("session",), False),
    ("get_project_schedule", ("session",), False),
    ("set_project_schedule", ("session",), False),
    ("update_project_schedule", ("session",), False),
    ("set_project_schedule_enabled", ("session",), False),
    ("get_project_graph", ("session",), False),
    ("validate_graph_changes", ("session",), False),
    ("apply_graph_changes", ("session",), True),
    ("auto_layout_project", ("session",), False),
    ("list_connections", ("session",), False),
    ("get_connection", ("session",), False),
    ("browse_database", ("redis",), False),
    ("get_database_table", ("redis",), False),
    ("query_database_readonly", (), False),
    ("list_storage", ("session",), False),
    ("preview_storage_file", ("session",), False),
    ("create_database", ("redis",), False),
    ("create_schema", ("redis",), False),
    ("create_table", ("redis",), False),
    ("resolve_write_columns", (), False),
    ("apply_table_column_actions", ("redis",), False),
    ("run_project", ("session",), True),
    ("get_task", ("session",), False),
    ("wait_task", ("session",), False),
    ("get_task_logs", ("session",), False),
    ("cancel_task", ("session", "orchestrator"), True),
]


def replace_handler(monkeypatch, name, handler):
    monkeypatch.setitem(registry.TOOLS, name, replace(registry.TOOLS[name], handler=handler))


@pytest.fixture
def request_context():
    return SimpleNamespace(
        session=AsyncMock(),
        principal=SimpleNamespace(
            user=SimpleNamespace(id="user"), token=SimpleNamespace(id="token")
        ),
        redis=object(),
        orchestrator=object(),
    )


async def invoke(context, name, arguments=None):
    return await handlers.call_tool(
        name,
        ToolCallSchema(arguments=arguments or {}),
        context.session,
        context.principal,
        context.redis,
        context.orchestrator,
        "correlation",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("name,dependencies,commits", DISPATCH_CASES)
async def test_dispatch_dependencies_response_and_commit(
    name,
    dependencies,
    commits,
    request_context,
    monkeypatch,
):
    events = []

    async def handler(**kwargs):
        assert kwargs["principal"] is request_context.principal
        assert set(kwargs) == {"principal", *dependencies} | (
            {"patch"} if name in {"validate_graph_changes", "apply_graph_changes"} else set()
        )
        for dependency in dependencies:
            assert kwargs[dependency] is getattr(request_context, dependency)
        if "patch" in kwargs:
            assert kwargs["patch"].add_nodes == []
        events.append("handler")
        return {"accepted": name}

    request_context.session.commit.side_effect = lambda: events.append("commit")
    replace_handler(monkeypatch, name, handler)
    result = await invoke(request_context, name)
    assert result.result == {"accepted": name}
    assert events == (["handler", "commit"] if commits else ["handler"])
    request_context.session.rollback.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("dry_run,commits", [(True, False), (False, True)])
async def test_layout_commits_only_when_applying(dry_run, commits, request_context, monkeypatch):
    handler = AsyncMock(return_value={"ok": True})
    replace_handler(monkeypatch, "auto_layout_project", handler)
    await invoke(request_context, "auto_layout_project", {"dry_run": dry_run})
    assert request_context.session.commit.await_count == int(commits)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name",
    [
        "create_project",
        "list_project_schedules",
        "get_project_graph",
        "resolve_write_columns",
        "apply_table_column_actions",
    ],
)
@pytest.mark.parametrize("reserved", ["session", "principal", "redis"])
async def test_reserved_arguments_rejected_before_handler(
    name, reserved, request_context, monkeypatch
):
    handler = AsyncMock()
    replace_handler(monkeypatch, name, handler)
    with pytest.raises(AIMCPHTTPError) as error:
        await invoke(request_context, name, {reserved: "forged"})
    assert error.value.detail == {
        "code": "INVALID_ARGUMENTS",
        "message": "Reserved tool arguments.",
    }
    handler.assert_not_awaited()
    request_context.session.rollback.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name,code,status",
    [
        ("create_project", "INVALID_ARGUMENTS", 422),
        ("get_project_graph", "INVALID_ARGUMENTS", 422),
        ("list_project_schedules", "INVALID_ARGUMENTS", 422),
        ("search_nodes", "GATEWAY_UNAVAILABLE", 500),
        ("resolve_write_columns", "GATEWAY_UNAVAILABLE", 500),
    ],
)
async def test_signature_mismatch_keeps_current_error_policy(
    name, code, status, request_context, monkeypatch
):
    entered = False

    async def handler(*, principal, session=None):
        nonlocal entered
        entered = True
        return {}

    replace_handler(monkeypatch, name, handler)
    with pytest.raises(AIMCPHTTPError) as error:
        await invoke(request_context, name, {"unexpected": True})
    assert (error.value.status_code, error.value.detail["code"]) == (status, code)
    assert not entered
    request_context.session.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_commit_failure_rolls_back_and_is_sanitized(request_context, monkeypatch):
    replace_handler(monkeypatch, "run_project", AsyncMock(return_value={"task_id": "task"}))
    request_context.session.commit.side_effect = RuntimeError("private database details")
    with pytest.raises(AIMCPHTTPError) as error:
        await invoke(request_context, "run_project")
    assert error.value.status_code == 500
    assert error.value.detail == {
        "code": "GATEWAY_UNAVAILABLE",
        "message": "Gateway operation failed.",
    }
    request_context.session.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_unknown_tool_does_not_touch_transaction_or_audit(request_context, monkeypatch):
    log = Mock()
    monkeypatch.setattr(handlers, "logger", log)
    with pytest.raises(AIMCPHTTPError) as error:
        await invoke(request_context, "missing")
    assert error.value.status_code == 404
    assert error.value.detail["code"] == "NODE_NOT_AVAILABLE"
    request_context.session.commit.assert_not_awaited()
    request_context.session.rollback.assert_not_awaited()
    log.bind.assert_not_called()


@pytest.mark.asyncio
async def test_audit_keeps_identity_before_rollback_and_does_not_log_patch(
    request_context, monkeypatch
):
    class Identity:
        @property
        def id(self):
            if expired:
                raise AssertionError("Identity read after rollback")
            return "actor"

    expired = False

    def expire():
        nonlocal expired
        expired = True

    request_context.principal.user = Identity()
    request_context.principal.token = Identity()
    request_context.session.rollback.side_effect = expire
    log = Mock()
    monkeypatch.setattr(handlers, "logger", log)
    patch = {"add_nodes": [{"ref": "new", "node_type": "Node", "comment": "private text"}]}
    denied = AIMCPHTTPError(403, "SCOPE_DENIED", "Denied.", details={"resource": "project"})
    replace_handler(monkeypatch, "apply_graph_changes", AsyncMock(side_effect=denied))
    with pytest.raises(AIMCPHTTPError) as error:
        await invoke(request_context, "apply_graph_changes", {"patch": patch})
    assert error.value is denied
    audit = log.bind.call_args.kwargs
    assert audit["user_id"] == audit["token_id"] == "actor"
    assert audit["correlation_id"] == "correlation"
    assert audit["outcome"] == "SCOPE_DENIED"
    assert audit["mutation_summary"] == {"add_nodes": 1}
    assert "private text" not in repr(audit)
    assert len(audit["patch_sha256"]) == 64


FAILURE_CASES = [
    (
        catalog_errors.CatalogSourceTimeoutError("private"),
        504,
        "QUERY_TIMEOUT",
        "Catalog request timed out.",
    ),
    (
        catalog_errors.CatalogRequestValidationError("private"),
        422,
        "GRAPH_VALIDATION_FAILED",
        "Catalog request arguments are invalid.",
    ),
    (
        catalog_errors.CatalogConnectionUnavailableError("private"),
        404,
        "CONNECTION_NOT_FOUND_OR_DENIED",
        "Connection or catalog object is unavailable.",
    ),
    (
        catalog_errors.CatalogTableNotFoundError("private"),
        404,
        "CONNECTION_NOT_FOUND_OR_DENIED",
        "Connection or catalog object is unavailable.",
    ),
    (
        catalog_errors.CatalogUnsupportedError("private"),
        404,
        "CONNECTION_NOT_FOUND_OR_DENIED",
        "Connection or catalog object is unavailable.",
    ),
    (
        storage_errors.StorageConnectionNotFoundError("private"),
        404,
        "CONNECTION_NOT_FOUND_OR_DENIED",
        "Connection or catalog object is unavailable.",
    ),
    (
        FileStorageDomainError("private"),
        422,
        "STORAGE_PREVIEW_UNSUPPORTED",
        "Storage operation or preview is not supported.",
    ),
    (
        storage_errors.FileTooLargeError(10),
        422,
        "STORAGE_PREVIEW_UNSUPPORTED",
        "Storage operation or preview is not supported.",
    ),
    (
        storage_errors.UnsupportedStorageBackendError("private"),
        422,
        "STORAGE_PREVIEW_UNSUPPORTED",
        "Storage operation or preview is not supported.",
    ),
    (
        storage_errors.UnsupportedTransferStrategyError("private", "read"),
        422,
        "STORAGE_PREVIEW_UNSUPPORTED",
        "Storage operation or preview is not supported.",
    ),
    (
        catalog_errors.CatalogCacheUnavailableError("private"),
        503,
        "GATEWAY_UNAVAILABLE",
        "Gateway dependency is unavailable.",
    ),
    (
        catalog_errors.CatalogSourceUnavailableError("private"),
        503,
        "GATEWAY_UNAVAILABLE",
        "Gateway dependency is unavailable.",
    ),
    (
        storage_errors.StorageOperationError("private"),
        503,
        "GATEWAY_UNAVAILABLE",
        "Gateway dependency is unavailable.",
    ),
    (TypeError("private"), 500, "GATEWAY_UNAVAILABLE", "Gateway operation failed."),
    (RuntimeError("private"), 500, "GATEWAY_UNAVAILABLE", "Gateway operation failed."),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("exception,status,code,message", FAILURE_CASES)
async def test_failure_translation_and_audit(
    exception, status, code, message, request_context, monkeypatch
):
    log = Mock()
    monkeypatch.setattr(handlers, "logger", log)
    replace_handler(monkeypatch, "create_project", AsyncMock(side_effect=exception))
    with pytest.raises(AIMCPHTTPError) as error:
        await invoke(request_context, "create_project")
    assert error.value.status_code == status
    assert error.value.detail == {"code": code, "message": message}
    assert error.value.__cause__ is exception
    request_context.session.rollback.assert_awaited_once()
    request_context.session.commit.assert_not_awaited()
    assert log.bind.call_args.kwargs["outcome"] == (
        "internal_error" if isinstance(exception, RuntimeError) else code
    )
    assert "private" not in repr(log.mock_calls)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name,code",
    [
        ("create_project", "INVALID_ARGUMENTS"),
        ("update_project_schedule", "INVALID_ARGUMENTS"),
        ("get_project_graph", "GRAPH_VALIDATION_FAILED"),
        ("query_database_readonly", "GRAPH_VALIDATION_FAILED"),
    ],
)
async def test_handler_value_error_keeps_tool_specific_code(
    name, code, request_context, monkeypatch
):
    replace_handler(monkeypatch, name, AsyncMock(side_effect=ValueError("private")))
    with pytest.raises(AIMCPHTTPError) as error:
        await invoke(request_context, name)
    assert error.value.status_code == 422
    assert error.value.detail == {
        "code": code,
        "message": "Tool arguments or graph changes are invalid.",
    }
    request_context.session.rollback.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "arguments,code,message",
    [
        (
            {"session": "forged", "patch": {"invalid": True}},
            "INVALID_ARGUMENTS",
            "Reserved tool arguments.",
        ),
        (
            {"patch": {"invalid": True}},
            "GRAPH_VALIDATION_FAILED",
            "Tool arguments or graph changes are invalid.",
        ),
    ],
)
async def test_graph_argument_validation_order(
    arguments, code, message, request_context, monkeypatch
):
    async def handler(*, principal, session, project_id, patch):
        raise AssertionError("Must not enter")

    replace_handler(monkeypatch, "apply_graph_changes", handler)
    with pytest.raises(AIMCPHTTPError) as error:
        await invoke(request_context, "apply_graph_changes", arguments)
    assert error.value.detail == {"code": code, "message": message}
    request_context.session.commit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "arguments,message",
    [
        ({"dry_run": "false", "unexpected": True}, "Tool arguments are invalid."),
        ({"dry_run": "false"}, "dry_run must be a boolean."),
    ],
)
async def test_layout_signature_is_checked_before_dry_run_type(
    arguments, message, request_context, monkeypatch
):
    async def handler(*, principal, session, dry_run=True):
        raise AssertionError("Must not enter")

    replace_handler(monkeypatch, "auto_layout_project", handler)
    with pytest.raises(AIMCPHTTPError) as error:
        await invoke(request_context, "auto_layout_project", arguments)
    assert error.value.detail == {"code": "INVALID_ARGUMENTS", "message": message}
    request_context.session.commit.assert_not_awaited()
