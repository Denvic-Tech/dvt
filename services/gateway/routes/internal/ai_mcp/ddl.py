from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from redis.asyncio import Redis

from services.gateway.routes.utils.DDL.connection import (
    invalidate_ddl_catalog,
    resolve_ddl_connection,
)
from services.gateway.routes.utils.DDL.database import (
    create_database_from_connection_string,
)
from services.gateway.routes.utils.DDL.schema import create_schema_from_connection_string
from services.gateway.routes.utils.DDL.table import create_table_from_connection_string

from src.schemas.http.create_table import (
    CreateDatabaseRequest,
    CreateSchemaRequest,
    CreateTableFromSchemaRequest,
)

from .access import get_accessible_connection
from .auth import MCPPrincipal
from .errors import AIMCPHTTPError


def _ddl_error(*, target_kind: str, exc: Exception) -> AIMCPHTTPError:
    normalized = str(exc).lower()
    if "not supported" in normalized or "unsupported" in normalized:
        return AIMCPHTTPError(
            422,
            "DDL_UNSUPPORTED",
            f"Creating this {target_kind} is not supported by the selected connection.",
        )
    return AIMCPHTTPError(
        422,
        "DDL_OPERATION_FAILED",
        f"Failed to create the requested {target_kind}.",
    )


async def _run_create_operation(
    *,
    principal: MCPPrincipal,
    redis: Redis,
    connection_id: str,
    target_kind: str,
    request: Any,
    operation: Callable[[Any, str], Any],
) -> dict[str, Any]:
    connection = await get_accessible_connection(principal, connection_id)
    if str(connection.kind).lower() != "sql":
        raise AIMCPHTTPError(
            404,
            "CONNECTION_NOT_FOUND_OR_DENIED",
            "Connection is unavailable for SQL DDL operations.",
        )

    try:
        resolved = await resolve_ddl_connection(connection_id, principal.user)
        response = await asyncio.to_thread(
            operation,
            request,
            resolved.connection_string,
        )
        await invalidate_ddl_catalog(
            connection_id=resolved.connection_id,
            user=principal.user,
            redis=redis,
        )
    except AIMCPHTTPError:
        raise
    except Exception as exc:
        raise _ddl_error(target_kind=target_kind, exc=exc) from exc

    return response.model_dump(mode="json")


async def create_database(
    *,
    principal: MCPPrincipal,
    redis: Redis,
    connection_id: str,
    database_name: str,
) -> dict[str, Any]:
    try:
        request = CreateDatabaseRequest(
            connection_id=connection_id,
            database_name=database_name,
        )
    except Exception as exc:
        raise _ddl_error(target_kind="database", exc=exc) from exc
    return await _run_create_operation(
        principal=principal,
        redis=redis,
        connection_id=connection_id,
        target_kind="database",
        request=request,
        operation=create_database_from_connection_string,
    )


async def create_schema(
    *,
    principal: MCPPrincipal,
    redis: Redis,
    connection_id: str,
    schema_name: str,
    database_name: str | None = None,
) -> dict[str, Any]:
    try:
        request = CreateSchemaRequest(
            connection_id=connection_id,
            database_name=database_name,
            schema_name=schema_name,
        )
    except Exception as exc:
        raise _ddl_error(target_kind="schema", exc=exc) from exc
    return await _run_create_operation(
        principal=principal,
        redis=redis,
        connection_id=connection_id,
        target_kind="schema",
        request=request,
        operation=create_schema_from_connection_string,
    )


async def create_table(
    *,
    principal: MCPPrincipal,
    redis: Redis,
    connection_id: str,
    table_name: str,
    columns: list[dict[str, Any]],
    database_name: str | None = None,
    schema_name: str | None = None,
    table_create_spec: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        request = CreateTableFromSchemaRequest(
            connection_id=connection_id,
            database_name=database_name,
            schema_name=schema_name,
            table_name=table_name,
            columns=columns,
            table_create_spec=table_create_spec,
            on_exists="ignore",
        )
    except Exception as exc:
        raise _ddl_error(target_kind="table", exc=exc) from exc
    return await _run_create_operation(
        principal=principal,
        redis=redis,
        connection_id=connection_id,
        target_kind="table",
        request=request,
        operation=create_table_from_connection_string,
    )
