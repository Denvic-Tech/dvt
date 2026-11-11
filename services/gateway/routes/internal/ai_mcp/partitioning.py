"""Read partitioning advice shared with the public Gateway route."""

from typing import Any

from pydantic import ValidationError

from services.gateway.routes.impl.partitioning_advice import (
    PartitioningAdviceError,
    PartitioningAdviceRequest,
    suggest_read_partitioning as _suggest_read_partitioning,
)
from services.gateway.routes.utils.DDL.connection import resolve_ddl_connection

from .access import get_accessible_connection
from .auth import MCPPrincipal
from .errors import AIMCPHTTPError


class _SuggestReadPartitioningRequest(PartitioningAdviceRequest):
    connection_id: str


def _request(arguments: dict[str, Any]) -> _SuggestReadPartitioningRequest:
    try:
        return _SuggestReadPartitioningRequest.model_validate(arguments)
    except (ValueError, ValidationError) as exc:
        raise AIMCPHTTPError(
            422,
            "INVALID_ARGUMENTS",
            "Partitioning advice arguments are invalid: pass connection_id and exactly one of "
            "table_name or sql_code.",
        ) from exc


async def _resolve_connection(principal: MCPPrincipal, connection_id: str):
    connection = await get_accessible_connection(principal, connection_id)
    if str(connection.kind).lower() != "sql":
        raise AIMCPHTTPError(
            404,
            "CONNECTION_NOT_FOUND_OR_DENIED",
            "Connection is unavailable for SQL partitioning advice.",
        )
    return await resolve_ddl_connection(connection_id, principal.user)


def _operation_error(exc: PartitioningAdviceError) -> AIMCPHTTPError:
    return AIMCPHTTPError(exc.status_code, exc.code, exc.message)


async def suggest_read_partitioning(*, principal: MCPPrincipal, **arguments: Any) -> dict[str, Any]:
    request = _request(arguments)
    resolved = await _resolve_connection(principal, request.connection_id)
    advice_request = PartitioningAdviceRequest.model_validate(
        request.model_dump(exclude={"connection_id"}, exclude_unset=True)
    )
    try:
        response = await _suggest_read_partitioning(resolved.connection_string, advice_request)
    except PartitioningAdviceError as exc:
        raise _operation_error(exc) from exc
    return response.model_dump(mode="json")
