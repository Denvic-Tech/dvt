from typing import Any

import sqlalchemy as sa
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.crud import graph as graph_crud
from src.models import AIAnalysisRequestRecord, LogRecord
from src.modules.project.infra.db_models import ProjectRecord
from src.modules.task_execution.infra.queries import TaskReadModel, get_accessible_task
from src.schemas.http.ai_analysis_service import (
    AIServiceAnalysisContextSchema,
    AIServiceAnalysisProjectSchema,
    AIServiceAnalysisTaskSchema,
    AIServiceLogEntrySchema,
    AIServiceLogErrorAnalysisCreateSchema,
    AIServicePipelineContextSchema,
    AIServicePipelineEdgeContextSchema,
    AIServicePipelineNodeContextSchema,
)
from src.version import get_version_from_pyproject

from .parsing import (
    extract_traceback_source_modules,
    resolve_node_source,
)

FAILED_NODE_PLACEHOLDER_ID = "__failed_node_placeholder__"
FAILED_NODE_PLACEHOLDER_NAME = "Failed node placeholder"
FAILED_NODE_PLACEHOLDER_TYPE = "UnknownFailedNode"
FAILED_NODE_PLACEHOLDER_SOURCE_MODULE = "src.ai_analysis.placeholder"
MAX_REMOTE_LOG_ENTRIES = 5


def _json_safe(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", by_alias=True)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    return value


def _task_to_remote_payload(task: TaskReadModel) -> AIServiceAnalysisTaskSchema:
    status_value = task.status.value if hasattr(task.status, "value") else str(task.status)
    return AIServiceAnalysisTaskSchema(
        id=task.task_id,
        status=status_value.lower(),
        mode=task.mode.value if hasattr(task.mode, "value") else str(task.mode),
        started_at=task.started_at,
        finished_at=task.finished_at,
    )


def _project_to_remote_payload(project: ProjectRecord) -> AIServiceAnalysisProjectSchema:
    return AIServiceAnalysisProjectSchema(id=project.id, name=project.name)


async def build_pipeline_context(
    session: AsyncSession,
    *,
    project: ProjectRecord,
) -> AIServicePipelineContextSchema:
    nodes, edges, _ = await graph_crud.get_graph_by(
        session,
        organization_id=project.organization_id,
        owner_user_id=project.user_id,
        project_id=project.id,
    )
    node_ids = {node.ui_id for node in nodes}
    filtered_edges = [
        edge
        for edge in edges
        if edge.source in node_ids and edge.target in node_ids
    ]

    upstream_map: dict[str, list[str]] = {}
    for edge in filtered_edges:
        upstream_map.setdefault(edge.target, [])
        if edge.source not in upstream_map[edge.target]:
            upstream_map[edge.target].append(edge.source)

    nodes_payload: list[AIServicePipelineNodeContextSchema] = []
    for node in sorted(nodes, key=lambda item: item.ui_id):
        source_module, source_file = resolve_node_source(node.name)
        nodes_payload.append(
            AIServicePipelineNodeContextSchema(
                id=node.ui_id,
                name=node.display_name or node.name,
                type=node.type,
                input_values=_json_safe(node.input_values or {}),
                upstream_node_ids=upstream_map.get(node.ui_id, []),
                source_module=source_module,
                source_file=source_file,
            )
        )

    edges_payload = [
        AIServicePipelineEdgeContextSchema(
            source_node_id=edge.source,
            target_node_id=edge.target,
            source_output=edge.source_handle.replace("output-", "") if edge.source_handle else None,
            target_input=edge.target_handle.replace("input-", "") if edge.target_handle else None,
        )
        for edge in filtered_edges
    ]

    return AIServicePipelineContextSchema(
        nodes=nodes_payload,
        edges=edges_payload,
    )


async def build_remote_logs(
    session: AsyncSession,
    *,
    task: TaskReadModel,
) -> tuple[list[AIServiceLogEntrySchema], str | None]:
    logs_stmt = (
        sa.select(LogRecord)
        .where(LogRecord.task_id == task.task_id)
        .order_by(sa.desc(LogRecord.created_at), sa.desc(LogRecord.id))
        .limit(MAX_REMOTE_LOG_ENTRIES)
    )
    log_entries = list((await session.execute(logs_stmt)).scalars().all())
    log_entries.reverse()

    traceback_stmt = (
        sa.select(LogRecord.exception_traceback)
        .where(
            LogRecord.task_id == task.task_id,
            LogRecord.exception_traceback.is_not(None),
        )
        .order_by(sa.desc(LogRecord.created_at), sa.desc(LogRecord.id))
        .limit(1)
    )
    traceback_text = (await session.execute(traceback_stmt)).scalar_one_or_none()

    logs_payload: list[AIServiceLogEntrySchema] = []
    for log_entry in log_entries:
        logs_payload.append(
            AIServiceLogEntrySchema(
                timestamp=log_entry.created_at,
                level=log_entry.level,
                service=log_entry.service_name,
                module=log_entry.module,
                function=log_entry.function,
                line=log_entry.line,
                message=log_entry.message,
            )
        )

    if not logs_payload:
        if task.message:
            logs_payload.append(AIServiceLogEntrySchema(level="ERROR", message=task.message))
        if task.termination_reason and task.termination_reason != task.message:
            logs_payload.append(AIServiceLogEntrySchema(level="ERROR", message=task.termination_reason))

    if traceback_text is None:
        traceback_text = task.termination_reason

    return logs_payload, traceback_text


async def build_remote_request_payload(
    session: AsyncSession,
    request: AIAnalysisRequestRecord,
    project: ProjectRecord,
) -> AIServiceLogErrorAnalysisCreateSchema:
    task_id = request.task_id
    if not task_id:
        raise RuntimeError("AI analysis request does not contain task_id")

    task = await get_accessible_task(
        session=session,
        organization_id=request.organization_id,
        owner_user_id=None,
        project_id=project.id,
        task_id=task_id,
    )
    if task is None:
        raise RuntimeError(f"Task ID={task_id} not found for AI analysis request")

    logs, traceback_text = await build_remote_logs(session, task=task)
    return AIServiceLogErrorAnalysisCreateSchema(
        idempotency_key=request.id,
        dvt_version=get_version_from_pyproject() or "unknown",
        task=_task_to_remote_payload(task),
        project=_project_to_remote_payload(project),
        pipeline_context=await build_pipeline_context(
            session,
            project=project,
        ),
        analysis_context=AIServiceAnalysisContextSchema(
            traceback_source_modules=extract_traceback_source_modules(traceback_text)
        ),
        logs=logs,
        traceback=traceback_text,
    )
