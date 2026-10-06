"""Scoped write-column operations shared with the public Gateway DDL routes."""

import asyncio
from typing import Any

from pydantic import ConfigDict, StrictBool, ValidationError
from redis.asyncio import Redis

from services.gateway.routes.utils.DDL.connection import (
    invalidate_ddl_catalog,
    resolve_ddl_connection,
)
from services.gateway.routes.utils.DDL.table import (
    apply_table_column_actions_from_connection_string,
    resolve_write_columns_from_connection_string,
)

from src.schemas.http.create_table import ApplyTableColumnActionsRequest, ResolveWriteColumnsRequest

from .access import get_accessible_connection
from .auth import MCPPrincipal
from .errors import AIMCPHTTPError


class _ResolveWriteColumnsRequest(ResolveWriteColumnsRequest):
    model_config = ConfigDict(extra="forbid")


class _ApplyTableColumnActionsRequest(ApplyTableColumnActionsRequest):
    model_config = ConfigDict(extra="forbid")

    # MCP previews by default; the public UI request keeps its existing default.
    dry_run: StrictBool = True


def _request(arguments: dict[str, Any], request_model):
    try:
        # Validate the original payload so omitted fields remain distinct from explicit null.
        return request_model.model_validate(arguments)
    except (ValueError, ValidationError) as exc:
        raise AIMCPHTTPError(
            422, "INVALID_ARGUMENTS", "Write-column arguments are invalid."
        ) from exc


async def _resolve_connection(principal: MCPPrincipal, connection_id: str):
    connection = await get_accessible_connection(principal, connection_id)
    if str(connection.kind).lower() != "sql":
        raise AIMCPHTTPError(
            404, "CONNECTION_NOT_FOUND_OR_DENIED",
            "Connection is unavailable for SQL DDL operations.",
        )
    return await resolve_ddl_connection(connection_id, principal.user)


def _operation_error(exc: Exception) -> AIMCPHTTPError:
    normalized = str(exc).lower()
    if "not supported" in normalized or "unsupported" in normalized:
        return AIMCPHTTPError(
            422, "DDL_UNSUPPORTED", "This column operation is not supported by the connection."
        )
    return AIMCPHTTPError(
        422, "DDL_OPERATION_FAILED",
        "Write-column operation failed. Inspect the target before planning remaining actions.",
    )


async def resolve_write_columns(
    *, principal: MCPPrincipal, **arguments: Any,
) -> dict[str, Any]:
    request = _request(arguments, _ResolveWriteColumnsRequest)
    resolved = await _resolve_connection(principal, request.connection_id)
    try:
        response = await resolve_write_columns_from_connection_string(
            request, resolved.connection_string,
        )
    except Exception as exc:
        raise _operation_error(exc) from exc
    return response.model_dump(mode="json")


async def apply_table_column_actions(
    *, principal: MCPPrincipal, redis: Redis, **arguments: Any,
) -> dict[str, Any]:
    request = _request(arguments, _ApplyTableColumnActionsRequest)
    resolved = await _resolve_connection(principal, request.connection_id)
    try:
        try:
            response = await asyncio.to_thread(
                apply_table_column_actions_from_connection_string,
                request,
                resolved.connection_string,
            )
        finally:
            # Some dialects commit earlier statements even when a later statement fails.
            if not request.dry_run:
                await invalidate_ddl_catalog(
                    connection_id=resolved.connection_id, user=principal.user, redis=redis,
                )
    except Exception as exc:
        raise _operation_error(exc) from exc
    return response.model_dump(mode="json")
