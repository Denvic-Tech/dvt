from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa
from db_connection import AccessDeniedError
from fastapi import HTTPException

from services.gateway.routes.utils.DDL import connection as connection_routes, table as table_routes

from src.schemas.http.common import CommonResponse
from src.schemas.http.create_table import CreateTableFromSQLRequest


@pytest.mark.asyncio
async def test_resolve_ddl_connection_loads_owned_record_and_renders_secret_server_side(
    monkeypatch,
) -> None:
    user = object()
    record = object()
    service = SimpleNamespace(get=AsyncMock(return_value=record))
    sql_record = SimpleNamespace(id="connection-1")

    monkeypatch.setattr(connection_routes, "get_connection_service", lambda: service)
    monkeypatch.setattr(connection_routes, "SqlConnectionRecord", lambda value: sql_record)
    monkeypatch.setattr(
        connection_routes,
        "resolve_sql_connection_url",
        lambda value: sa.engine.make_url("postgresql://user:secret@db/catalog"),
    )

    resolved = await connection_routes.resolve_ddl_connection(
        "connection-1",
        user,
    )

    service.get.assert_awaited_once_with("connection-1", actor=user)
    assert resolved.connection_id == "connection-1"
    assert resolved.connection_string == "postgresql://user:secret@db/catalog"


@pytest.mark.asyncio
async def test_resolve_ddl_connection_hides_access_denial_as_not_found(monkeypatch) -> None:
    service = SimpleNamespace(
        get=AsyncMock(side_effect=AccessDeniedError("denied")),
    )
    monkeypatch.setattr(connection_routes, "get_connection_service", lambda: service)

    with pytest.raises(HTTPException) as exc_info:
        await connection_routes.resolve_ddl_connection(
            "foreign-connection",
            object(),
        )

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_resolve_ddl_connection_rejects_non_sql_record(monkeypatch) -> None:
    service = SimpleNamespace(get=AsyncMock(return_value=object()))
    monkeypatch.setattr(connection_routes, "get_connection_service", lambda: service)

    def reject_non_sql(_record):
        raise TypeError("not SQL")

    monkeypatch.setattr(connection_routes, "SqlConnectionRecord", reject_non_sql)

    with pytest.raises(HTTPException) as exc_info:
        await connection_routes.resolve_ddl_connection(
            "s3-connection",
            object(),
        )

    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_catalog_invalidation_uses_refresh_epoch(monkeypatch) -> None:
    execute = AsyncMock()
    use_cases = SimpleNamespace(refresh=SimpleNamespace(execute=execute))
    user = SimpleNamespace(id="user-1", organization_id="org-1", role="admin")
    monkeypatch.setattr(
        connection_routes,
        "get_catalog_use_cases",
        lambda _redis: use_cases,
    )

    await connection_routes.invalidate_ddl_catalog(
        connection_id="connection-1",
        user=user,
        redis=object(),
    )

    execute.assert_awaited_once()
    assert execute.await_args.kwargs["connection_id"] == "connection-1"
    assert execute.await_args.kwargs["actor"].id == "user-1"


@pytest.mark.asyncio
async def test_create_table_invalidates_catalog_after_success(monkeypatch) -> None:
    request = CreateTableFromSQLRequest(
        connection_id="connection-1",
        table_ddl="CREATE TABLE items (id INTEGER)",
    )
    invalidate = AsyncMock()
    user = object()
    redis = object()

    async def resolve(_reference, _user):
        return connection_routes.ResolvedDDLConnection(
            connection_id="connection-1",
            connection_string="sqlite://",
        )

    async def to_thread(fn, *args):
        assert fn is table_routes.create_table_from_connection_string
        return CommonResponse(success=True, message="created")

    monkeypatch.setattr(table_routes, "resolve_ddl_connection", resolve)
    monkeypatch.setattr(table_routes, "invalidate_ddl_catalog", invalidate)
    monkeypatch.setattr(table_routes.asyncio, "to_thread", to_thread)

    response = await table_routes.create_table(request, user, redis)

    assert response.message == "created"
    invalidate.assert_awaited_once_with(
        connection_id="connection-1",
        user=user,
        redis=redis,
    )
