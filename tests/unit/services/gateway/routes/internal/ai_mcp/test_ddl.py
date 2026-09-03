from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services.gateway.routes.internal.ai_mcp import ddl
from services.gateway.routes.internal.ai_mcp.errors import AIMCPHTTPError

from src.schemas.http.common import CommonResponse


@pytest.mark.asyncio
async def test_create_table_uses_scoped_connection_and_invalidates_catalog(monkeypatch) -> None:
    user = object()
    principal = SimpleNamespace(user=user)
    redis = object()
    request_capture = {}

    monkeypatch.setattr(
        ddl,
        "get_accessible_connection",
        AsyncMock(return_value=SimpleNamespace(kind="sql")),
    )
    monkeypatch.setattr(
        ddl,
        "resolve_ddl_connection",
        AsyncMock(
            return_value=SimpleNamespace(
                connection_id="connection-1",
                connection_string="sqlite://",
            )
        ),
    )

    def create_table(request, connection_string):
        request_capture["request"] = request
        request_capture["connection_string"] = connection_string
        return CommonResponse(success=True, message="created")

    invalidate = AsyncMock()
    monkeypatch.setattr(ddl, "create_table_from_connection_string", create_table)
    monkeypatch.setattr(ddl, "invalidate_ddl_catalog", invalidate)

    result = await ddl.create_table(
        principal=principal,
        redis=redis,
        connection_id="connection-1",
        table_name="target_table",
        columns=[{"name": "id", "dtype": "INT", "nullable": False}],
        schema_name="analytics",
        table_create_spec={"primary_key_cols": ["id"]},
    )

    request = request_capture["request"]
    assert request.connection_id == "connection-1"
    assert request.table_name == "target_table"
    assert request.on_exists == "ignore"
    assert request.columns[0].name == "id"
    assert request_capture["connection_string"] == "sqlite://"
    assert result == {"success": True, "message": "created"}
    invalidate.assert_awaited_once_with(
        connection_id="connection-1",
        user=user,
        redis=redis,
    )


@pytest.mark.asyncio
async def test_ddl_rejects_non_sql_connection_without_resolving_secret(monkeypatch) -> None:
    monkeypatch.setattr(
        ddl,
        "get_accessible_connection",
        AsyncMock(return_value=SimpleNamespace(kind="file")),
    )
    resolve = AsyncMock()
    monkeypatch.setattr(ddl, "resolve_ddl_connection", resolve)

    with pytest.raises(AIMCPHTTPError) as raised:
        await ddl.create_schema(
            principal=SimpleNamespace(user=object()),
            redis=object(),
            connection_id="s3-connection",
            schema_name="analytics",
        )

    assert raised.value.detail["code"] == "CONNECTION_NOT_FOUND_OR_DENIED"
    resolve.assert_not_awaited()


@pytest.mark.asyncio
async def test_ddl_failure_does_not_expose_driver_exception(monkeypatch) -> None:
    monkeypatch.setattr(
        ddl,
        "get_accessible_connection",
        AsyncMock(return_value=SimpleNamespace(kind="sql")),
    )
    monkeypatch.setattr(
        ddl,
        "resolve_ddl_connection",
        AsyncMock(
            return_value=SimpleNamespace(
                connection_id="connection-1",
                connection_string="postgresql://user:secret@host/db",
            )
        ),
    )

    def fail(_request, _connection_string):
        raise RuntimeError("password=secret host=private-db")

    monkeypatch.setattr(ddl, "create_database_from_connection_string", fail)

    with pytest.raises(AIMCPHTTPError) as raised:
        await ddl.create_database(
            principal=SimpleNamespace(user=object()),
            redis=object(),
            connection_id="connection-1",
            database_name="analytics",
        )

    assert raised.value.detail == {
        "code": "DDL_OPERATION_FAILED",
        "message": "Failed to create the requested database.",
    }
