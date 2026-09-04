from __future__ import annotations

import hashlib
import time
from collections.abc import Awaitable, Callable
from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Depends, Header
from pydantic import ValidationError

from services.gateway.deps import clients as client_deps
from services.gateway.deps.ai_mcp import require_ai_mcp_enabled
from services.gateway.deps.db_catalog import RedisBytes

from src.clients.orchestrator_client import GrpcOrchestratorClient
from src.db.fastapi.dependencies import AsyncSessionDepends
from src.logger import logger
from src.modules.db_catalog.domain.exceptions import (
    CatalogCacheUnavailableError,
    CatalogConnectionUnavailableError,
    CatalogRequestValidationError,
    CatalogSourceTimeoutError,
    CatalogSourceUnavailableError,
    CatalogTableNotFoundError,
    CatalogUnsupportedError,
)
from src.modules.file_storage.domain.exceptions import FileStorageDomainError
from src.modules.file_storage.flow.exceptions import (
    FileTooLargeError,
    StorageConnectionNotFoundError,
    StorageOperationError,
    UnsupportedStorageBackendError,
    UnsupportedTransferStrategyError,
)

from . import context, data, ddl, graph, tasks
from .auth import MCPPrincipalDepends
from .errors import AIMCPHTTPError
from .schemas import AuthVerificationSchema, ToolCallSchema, ToolResultSchema

router = APIRouter(
    prefix="/internal/ai-mcp/v1",
    include_in_schema=False,
    dependencies=[Depends(require_ai_mcp_enabled)],
)

ToolHandler = Callable[..., Awaitable[dict[str, Any]]]

_CONTEXT_HANDLERS: dict[str, ToolHandler] = {
    "list_projects": context.list_projects,
    "get_project": context.get_project,
    "search_nodes": context.search_nodes,
    "get_node_definition": context.get_node_definition,
}
_GRAPH_HANDLERS: dict[str, ToolHandler] = {
    "get_project_graph": graph.get_project_graph,
    "validate_graph_changes": graph.validate_graph_changes,
    "apply_graph_changes": graph.apply_graph_changes,
}
_DATA_HANDLERS: dict[str, ToolHandler] = {
    "list_connections": data.list_connections,
    "get_connection": data.get_connection,
    "browse_database": data.browse_database,
    "get_database_table": data.get_database_table,
    "query_database_readonly": data.query_database_readonly,
    "list_storage": data.list_storage,
    "preview_storage_file": data.preview_storage_file,
}
_DDL_HANDLERS: dict[str, ToolHandler] = {
    "create_database": ddl.create_database,
    "create_schema": ddl.create_schema,
    "create_table": ddl.create_table,
}
_TASK_HANDLERS: dict[str, ToolHandler] = {
    "run_project": tasks.run_project,
    "get_task": tasks.get_task,
    "wait_task": tasks.wait_task,
    "get_task_logs": tasks.get_task_logs,
    "cancel_task": tasks.cancel_task,
}


def _safe_operation_summary(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "project_id": arguments.get("project_id"),
        "connection_id": arguments.get("connection_id"),
        "task_id": arguments.get("task_id"),
    }
    for key in ("sql", "patch"):
        value = arguments.get(key)
        if value is not None:
            encoded = repr(value).encode("utf-8")
            summary[f"{key}_sha256"] = hashlib.sha256(encoded).hexdigest()
            summary[f"{key}_bytes"] = len(encoded)
    if tool_name == "apply_graph_changes":
        patch = arguments.get("patch") or {}
        summary["mutation_summary"] = {
            key: len(value) if isinstance(value, list) else 0 for key, value in patch.items()
        }
    return {key: value for key, value in summary.items() if value is not None}


@router.post("/auth/verify", response_model=AuthVerificationSchema)
async def verify_auth(principal: MCPPrincipalDepends) -> AuthVerificationSchema:
    return AuthVerificationSchema(
        user_id=principal.user.id,
        token_id=principal.token.id,
        access_scope=principal.token.access_scope.to_mapping(),
    )


@router.post("/tools/{tool_name}", response_model=ToolResultSchema)
async def call_tool(
    tool_name: str,
    payload: ToolCallSchema,
    session: AsyncSessionDepends,
    principal: MCPPrincipalDepends,
    redis: RedisBytes,
    orchestrator: Annotated[
        GrpcOrchestratorClient,
        Depends(client_deps.get_orchestrator_client),
    ],
    correlation_header: Annotated[str | None, Header(alias="X-Correlation-ID")] = None,
) -> ToolResultSchema:
    correlation_id = correlation_header or str(uuid4())
    started = time.monotonic()
    handler = (
        _CONTEXT_HANDLERS.get(tool_name)
        or _GRAPH_HANDLERS.get(tool_name)
        or _DATA_HANDLERS.get(tool_name)
        or _DDL_HANDLERS.get(tool_name)
        or _TASK_HANDLERS.get(tool_name)
    )
    if handler is None:
        raise AIMCPHTTPError(404, "NODE_NOT_AVAILABLE", "MCP tool is not available.")

    # AsyncSession.rollback() expires ORM-backed identities.  Keep the audit
    # identifiers as plain values so an expected tool error cannot trigger an
    # implicit lazy load from the finally block and mask the structured error.
    user_id = principal.user.id
    token_id = principal.token.id
    outcome = "success"
    try:
        kwargs: dict[str, Any] = {"principal": principal, **payload.arguments}
        if tool_name in {"validate_graph_changes", "apply_graph_changes"}:
            kwargs["patch"] = graph.GraphPatchSchema.model_validate(kwargs.get("patch", {}))
        if (
            tool_name in _CONTEXT_HANDLERS
            or tool_name in _GRAPH_HANDLERS
            or tool_name
            in {
                "list_connections",
                "get_connection",
                "list_storage",
                "preview_storage_file",
                "run_project",
                "get_task",
                "wait_task",
                "get_task_logs",
                "cancel_task",
            }
        ):
            kwargs["session"] = session
        if tool_name in {"browse_database", "get_database_table"}:
            kwargs["redis"] = redis
        if tool_name in _DDL_HANDLERS:
            kwargs["redis"] = redis
        if tool_name == "cancel_task":
            kwargs["orchestrator"] = orchestrator

        result = await handler(**kwargs)
        if tool_name in {"apply_graph_changes", "run_project", "cancel_task"}:
            await session.commit()
        return ToolResultSchema(result=result)
    except AIMCPHTTPError as exc:
        outcome = str(exc.detail.get("code", "error"))
        await session.rollback()
        raise
    except CatalogSourceTimeoutError as exc:
        outcome = "QUERY_TIMEOUT"
        await session.rollback()
        raise AIMCPHTTPError(504, "QUERY_TIMEOUT", "Catalog request timed out.") from exc
    except CatalogRequestValidationError as exc:
        outcome = "GRAPH_VALIDATION_FAILED"
        await session.rollback()
        raise AIMCPHTTPError(
            422,
            "GRAPH_VALIDATION_FAILED",
            "Catalog request arguments are invalid.",
        ) from exc
    except (
        CatalogConnectionUnavailableError,
        CatalogTableNotFoundError,
        CatalogUnsupportedError,
        StorageConnectionNotFoundError,
    ) as exc:
        outcome = "CONNECTION_NOT_FOUND_OR_DENIED"
        await session.rollback()
        raise AIMCPHTTPError(
            404,
            "CONNECTION_NOT_FOUND_OR_DENIED",
            "Connection or catalog object is unavailable.",
        ) from exc
    except (
        FileStorageDomainError,
        FileTooLargeError,
        UnsupportedStorageBackendError,
        UnsupportedTransferStrategyError,
    ) as exc:
        outcome = "STORAGE_PREVIEW_UNSUPPORTED"
        await session.rollback()
        raise AIMCPHTTPError(
            422,
            "STORAGE_PREVIEW_UNSUPPORTED",
            "Storage operation or preview is not supported.",
        ) from exc
    except (
        CatalogCacheUnavailableError,
        CatalogSourceUnavailableError,
        StorageOperationError,
    ) as exc:
        outcome = "GATEWAY_UNAVAILABLE"
        await session.rollback()
        raise AIMCPHTTPError(
            503,
            "GATEWAY_UNAVAILABLE",
            "Gateway dependency is unavailable.",
        ) from exc
    except TypeError as exc:
        outcome = "GATEWAY_UNAVAILABLE"
        await session.rollback()
        logger.error(
            "AI MCP tool contract mismatch: tool={} correlation_id={} exception_type={}",
            tool_name,
            correlation_id,
            type(exc).__name__,
        )
        raise AIMCPHTTPError(500, "GATEWAY_UNAVAILABLE", "Gateway operation failed.") from exc
    except (ValueError, ValidationError) as exc:
        outcome = "GRAPH_VALIDATION_FAILED"
        await session.rollback()
        raise AIMCPHTTPError(
            422,
            "GRAPH_VALIDATION_FAILED",
            "Tool arguments or graph changes are invalid.",
        ) from exc
    except Exception as exc:
        outcome = "internal_error"
        await session.rollback()
        logger.error(
            "AI MCP internal tool failed: tool={} correlation_id={} exception_type={}",
            tool_name,
            correlation_id,
            type(exc).__name__,
        )
        raise AIMCPHTTPError(500, "GATEWAY_UNAVAILABLE", "Gateway operation failed.") from exc
    finally:
        logger.bind(
            correlation_id=correlation_id,
            tool=tool_name,
            user_id=user_id,
            token_id=token_id,
            duration_ms=round((time.monotonic() - started) * 1000, 3),
            outcome=outcome,
            **_safe_operation_summary(tool_name, payload.arguments),
        ).info("AI MCP tool call")
