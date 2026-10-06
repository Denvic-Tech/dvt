"""HTTP entrypoints: prepare, invoke, commit or roll back, and audit."""

import hashlib
import time
from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Depends, Header

from services.gateway.deps import clients as client_deps
from services.gateway.deps.ai_mcp import require_ai_mcp_enabled
from services.gateway.deps.db_catalog import RedisBytes

from src.clients.orchestrator_client import GrpcOrchestratorClient
from src.db.fastapi.dependencies import AsyncSessionDepends
from src.logger import logger

from ..auth import MCPPrincipalDepends
from ..schemas import AuthVerificationSchema, ToolCallSchema, ToolResultSchema
from .arguments import prepare_arguments
from .failures import translate_failure
from .registry import get_tool

router = APIRouter(
    prefix="/internal/ai-mcp/v1",
    include_in_schema=False,
    dependencies=[Depends(require_ai_mcp_enabled)],
)


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
    if tool_name == "auto_layout_project":
        summary["dry_run"] = arguments.get("dry_run", True)
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
    tool = get_tool(tool_name)

    # Rollback expires ORM identities; audit must use values captured before it.
    user_id, token_id = principal.user.id, principal.token.id
    outcome = "success"
    try:
        arguments = prepare_arguments(
            tool_name,
            tool,
            payload.arguments,
            principal=principal,
            session=session,
            redis=redis,
            orchestrator=orchestrator,
        )
        result = await tool.handler(**arguments)
        if tool.should_commit(arguments):
            await session.commit()
        return ToolResultSchema(result=result)
    except Exception as exc:
        failure = translate_failure(exc, tool.validation_error_code)
        outcome = failure.outcome
        await session.rollback()
        if failure.log_message is not None:
            logger.error(failure.log_message, tool_name, correlation_id, type(exc).__name__)
        if failure.response is exc:
            raise
        raise failure.response from exc
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
