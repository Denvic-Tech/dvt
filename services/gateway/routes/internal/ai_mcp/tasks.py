from __future__ import annotations

import asyncio
import base64
import json
from datetime import datetime
from typing import Any

import sqlalchemy as sa

from services.gateway.routes.impl import task as task_impl

from src.clients.orchestrator_client import GrpcOrchestratorClient
from src.crud import graph as graph_crud
from src.models import LogRecord
from src.modules.task_execution.domain.types import (
    TERMINAL_STATUSES,
    TaskExecutionStatus,
    TaskSource,
)
from src.modules.task_execution.infra.queries import get_accessible_task
from src.pipeline.execution_mode import PipelineExecutionMode
from src.schemas.http.project_variable import ProjectVariableBase
from src.utils.access_control import get_access_scope

from .access import get_accessible_connection, get_accessible_project
from .auth import MCPPrincipal
from .errors import AIMCPHTTPError, denied
from .graph import analyze_graph_connection_dependencies
from .redaction import redact_log_message


def _task_payload(task) -> dict[str, Any]:
    return {
        "task_id": task.task_id,
        "project_id": task.project_id,
        "status": task.status.value,
        "source": task.source.value,
        "mode": task.mode.value,
        "force_exec": task.force_exec,
        "queued_at": task.queued_at.isoformat(),
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "finished_at": task.finished_at.isoformat() if task.finished_at else None,
        "updated_at": task.updated_at.isoformat(),
        "message": redact_log_message(task.message),
        "termination_reason": (
            task.termination_reason.value
            if hasattr(task.termination_reason, "value")
            else task.termination_reason
        ),
        "terminal": task.status in TERMINAL_STATUSES,
    }


async def _get_task(*, session, principal: MCPPrincipal, project_id: str, task_id: str):
    await get_accessible_project(session, principal, project_id)
    access_scope = get_access_scope(principal.user)
    task = await get_accessible_task(
        session,
        task_id=task_id,
        project_id=project_id,
        organization_id=access_scope.organization_id,
        owner_user_id=access_scope.owner_user_id,
    )
    if task is None:
        raise denied("task")
    return task


async def _check_execution_connections(
    *,
    session,
    principal: MCPPrincipal,
    project_id: str,
    target_node_ids: list[str] | None,
) -> None:
    nodes, _, _ = await graph_crud.get_graph_by(
        session=session,
        project_id=project_id,
        target_nodes=target_node_ids,
    )
    if target_node_ids:
        actual_ids = {node.ui_id for node in nodes}
        missing = sorted(set(target_node_ids) - actual_ids)
        if missing:
            raise AIMCPHTTPError(
                422,
                "GRAPH_VALIDATION_FAILED",
                "One or more target nodes do not exist.",
                details={"target_node_ids": missing},
            )
    connection_ids, unresolved = analyze_graph_connection_dependencies(
        nodes,
        project_id=project_id,
    )
    if unresolved:
        raise AIMCPHTTPError(
            403,
            "SCOPE_DENIED",
            "Execution contains dynamic or unresolved connection dependencies.",
            details={"inputs": unresolved},
        )
    for connection_id in sorted(connection_ids):
        await get_accessible_connection(principal, connection_id)


async def run_project(
    *,
    session,
    principal: MCPPrincipal,
    project_id: str,
    target_node_ids: list[str] | None = None,
    runtime_variables: dict[str, Any] | None = None,
    force_exec: bool = False,
) -> dict[str, Any]:
    project = await get_accessible_project(session, principal, project_id)
    target_node_ids = list(dict.fromkeys(target_node_ids or [])) or None
    await _check_execution_connections(
        session=session,
        principal=principal,
        project_id=project_id,
        target_node_ids=target_node_ids,
    )
    try:
        variables = (
            {
                key: ProjectVariableBase.model_validate(value)
                for key, value in runtime_variables.items()
            }
            if runtime_variables is not None
            else None
        )
    except (TypeError, ValueError) as exc:
        raise AIMCPHTTPError(
            422,
            "GRAPH_VALIDATION_FAILED",
            "Runtime variables are invalid.",
        ) from exc

    response = await task_impl.create_task_route_impl(
        session=session,
        project=project,
        user=principal.user,
        target_nodes=target_node_ids,
        mode=PipelineExecutionMode.FULL,
        force_exec=force_exec,
        source=TaskSource.MCP,
        variables=variables,
    )
    return {"task_id": response.task_id, "status": TaskExecutionStatus.QUEUED.value}


async def get_task(
    *, session, principal: MCPPrincipal, project_id: str, task_id: str
) -> dict[str, Any]:
    return _task_payload(
        await _get_task(
            session=session,
            principal=principal,
            project_id=project_id,
            task_id=task_id,
        )
    )


async def wait_task(
    *,
    session,
    principal: MCPPrincipal,
    project_id: str,
    task_id: str,
    timeout_sec: float = 20,
) -> dict[str, Any]:
    timeout_sec = max(0.0, min(float(timeout_sec), 50.0))
    deadline = asyncio.get_running_loop().time() + timeout_sec
    while True:
        task = await _get_task(
            session=session,
            principal=principal,
            project_id=project_id,
            task_id=task_id,
        )
        if task.status in TERMINAL_STATUSES or asyncio.get_running_loop().time() >= deadline:
            return _task_payload(task)
        await asyncio.sleep(min(0.5, max(0.0, deadline - asyncio.get_running_loop().time())))


def _encode_log_cursor(created_at: datetime, log_id: str) -> str:
    payload = json.dumps(
        {"created_at": created_at.isoformat(), "id": log_id},
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_log_cursor(cursor: str | None) -> tuple[datetime, str] | None:
    if not cursor:
        return None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode()))
        return datetime.fromisoformat(payload["created_at"]), str(payload["id"])
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise AIMCPHTTPError(422, "GRAPH_VALIDATION_FAILED", "Invalid log cursor.") from exc


async def get_task_logs(
    *,
    session,
    principal: MCPPrincipal,
    project_id: str,
    task_id: str,
    cursor: str | None = None,
    limit: int = 100,
    level: str | None = None,
) -> dict[str, Any]:
    await _get_task(
        session=session,
        principal=principal,
        project_id=project_id,
        task_id=task_id,
    )
    limit = max(1, min(int(limit), 500))
    filters = [LogRecord.task_id == task_id]
    if level:
        filters.append(LogRecord.level == level.upper())
    decoded_cursor = _decode_log_cursor(cursor)
    if decoded_cursor is not None:
        created_at, log_id = decoded_cursor
        filters.append(
            sa.or_(
                LogRecord.created_at > created_at,
                sa.and_(LogRecord.created_at == created_at, LogRecord.id > log_id),
            )
        )
    rows = list(
        (
            await session.execute(
                sa.select(LogRecord)
                .where(*filters)
                .order_by(LogRecord.created_at.asc(), LogRecord.id.asc())
                .limit(limit + 1)
            )
        )
        .scalars()
        .all()
    )
    has_more = len(rows) > limit
    page = rows[:limit]
    return {
        "items": [
            {
                "id": item.id,
                "created_at": item.created_at.isoformat(),
                "level": item.level,
                "service_name": item.service_name,
                "message": redact_log_message(item.message),
                "module": item.module,
                "function": item.function,
                "line": item.line,
            }
            for item in page
        ],
        "next_cursor": (
            _encode_log_cursor(page[-1].created_at, page[-1].id) if page and has_more else None
        ),
    }


async def cancel_task(
    *,
    session,
    principal: MCPPrincipal,
    orchestrator: GrpcOrchestratorClient,
    project_id: str,
    task_id: str,
) -> dict[str, Any]:
    task = await _get_task(
        session=session,
        principal=principal,
        project_id=project_id,
        task_id=task_id,
    )
    if task.status in TERMINAL_STATUSES:
        return _task_payload(task)
    await orchestrator.cancel_task(task_id=task.task_id)
    return {"task_id": task.task_id, "status": "CANCEL_REQUESTED"}
