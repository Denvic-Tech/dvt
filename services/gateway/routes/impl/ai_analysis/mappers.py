from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from src.enums import AIAnalysisStatus
from src.models import AIAnalysisRequestRecord
from src.schemas.http.ai_analysis import AIAnalysisHistoryItemSchema, AIAnalysisReadSchema
from src.schemas.http.ai_analysis_service import (
    AIServiceAnalysisRequestReadSchema,
    AIServiceAnalysisResultSchema,
    AIServiceAnalysisStatus,
)

NON_TERMINAL_STATUSES = {AIAnalysisStatus.QUEUED, AIAnalysisStatus.RUNNING}


def utcnow() -> datetime:
    return datetime.now(tz=UTC)


def is_terminal_status(status_value: AIAnalysisStatus) -> bool:
    return status_value not in NON_TERMINAL_STATUSES


def map_remote_status(
    status_value: AIServiceAnalysisStatus | str | None,
) -> tuple[AIAnalysisStatus, str | None]:
    normalized_status = (
        status_value.value if isinstance(status_value, AIServiceAnalysisStatus) else str(status_value or "")
    ).strip().lower()
    if normalized_status == AIServiceAnalysisStatus.CANCELLED.value:
        return AIAnalysisStatus.ERROR, "AI service request was cancelled"
    try:
        return AIAnalysisStatus(normalized_status), None
    except ValueError:
        return AIAnalysisStatus.ERROR, None


async def apply_remote_payload(
    session: AsyncSession,
    *,
    request: AIAnalysisRequestRecord,
    remote_payload: AIServiceAnalysisRequestReadSchema,
) -> AIAnalysisRequestRecord:
    local_status, default_error = map_remote_status(remote_payload.status)
    request.status = local_status

    if remote_payload.result is not None:
        request.result = remote_payload.result.model_dump(mode="json")
        request.title = remote_payload.result.title

    if (
        remote_payload.error is not None
        or default_error is not None
        or local_status in {AIAnalysisStatus.SUCCESS, AIAnalysisStatus.ERROR}
    ):
        request.error = (
            remote_payload.error
            or default_error
            or ("AI service request failed" if local_status == AIAnalysisStatus.ERROR else None)
        )

    if remote_payload.started_at is not None:
        request.started_at = remote_payload.started_at

    if remote_payload.finished_at is not None:
        request.finished_at = remote_payload.finished_at
    elif is_terminal_status(local_status):
        request.finished_at = request.finished_at or utcnow()

    await session.flush()
    await session.refresh(request)
    return request


def _to_public_result(result: dict | None) -> AIServiceAnalysisResultSchema | None:
    if result is None:
        return None
    return AIServiceAnalysisResultSchema.model_validate(result)


def request_to_read_schema(request: AIAnalysisRequestRecord) -> AIAnalysisReadSchema:
    return AIAnalysisReadSchema(
        request_id=request.id,
        project_id=request.project_id,
        status=request.status,
        title=request.title,
        result=_to_public_result(request.result),
        error=request.error,
        created_at=request.created_at,
        updated_at=request.updated_at,
        started_at=request.started_at,
        finished_at=request.finished_at,
    )


def request_to_history_item(request: AIAnalysisRequestRecord) -> AIAnalysisHistoryItemSchema:
    return AIAnalysisHistoryItemSchema(
        request_id=request.id,
        project_id=request.project_id,
        task_id=request.task_id,
        status=request.status,
        title=request.title,
        created_at=request.created_at,
        updated_at=request.updated_at,
        started_at=request.started_at,
        finished_at=request.finished_at,
        error=request.error,
    )
