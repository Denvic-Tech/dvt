from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src.enums import AIAnalysisStatus
from src.models import AIAnalysisRequestRecord


def _build_ai_analysis_filters(
    *,
    project_id: str | None = None,
    organization_id: str | None = None,
    owner_user_id: str | None = None,
    status: AIAnalysisStatus | None = None,
    task_id: str | None = None,
) -> list[sa.ColumnExpressionArgument[bool]]:
    filters: list[sa.ColumnExpressionArgument[bool]] = []
    if project_id is not None:
        filters.append(AIAnalysisRequestRecord.project_id == project_id)
    if organization_id is not None:
        filters.append(AIAnalysisRequestRecord.organization_id == organization_id)
    if owner_user_id is not None:
        filters.append(AIAnalysisRequestRecord.user_id == owner_user_id)
    if status is not None:
        filters.append(AIAnalysisRequestRecord.status == status)
    if task_id is not None:
        filters.append(AIAnalysisRequestRecord.task_id == task_id)
    return filters


async def create_ai_analysis_request(
    session: AsyncSession,
    *,
    task_id: str,
    project_id: str,
    user_id: str,
    organization_id: str,
    context: dict[str, Any] | None = None,
) -> AIAnalysisRequestRecord:
    request = AIAnalysisRequestRecord(
        task_id=task_id,
        project_id=project_id,
        user_id=user_id,
        organization_id=organization_id,
        context=context,
    )
    session.add(request)
    await session.flush()
    await session.refresh(request)
    return request


async def get_ai_analysis_request_by_id(
    session: AsyncSession,
    *,
    request_id: str,
    project_id: str | None = None,
    organization_id: str | None = None,
    owner_user_id: str | None = None,
) -> AIAnalysisRequestRecord | None:
    stmt = sa.select(AIAnalysisRequestRecord).where(
        AIAnalysisRequestRecord.id == request_id,
        *_build_ai_analysis_filters(
            project_id=project_id,
            organization_id=organization_id,
            owner_user_id=owner_user_id,
        ),
    )
    return (await session.execute(stmt)).scalars().first()


async def list_ai_analysis_requests(
    session: AsyncSession,
    *,
    project_id: str,
    organization_id: str | None = None,
    owner_user_id: str | None = None,
    status: AIAnalysisStatus | None = None,
    task_id: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[AIAnalysisRequestRecord]:
    stmt = (
        sa.select(AIAnalysisRequestRecord)
        .where(
            *_build_ai_analysis_filters(
                project_id=project_id,
                organization_id=organization_id,
                owner_user_id=owner_user_id,
                status=status,
                task_id=task_id,
            )
        )
        .order_by(sa.desc(AIAnalysisRequestRecord.created_at), sa.desc(AIAnalysisRequestRecord.id))
        .limit(limit)
        .offset(offset)
    )
    return list((await session.execute(stmt)).scalars().all())


async def count_ai_analysis_requests(
    session: AsyncSession,
    *,
    project_id: str,
    organization_id: str | None = None,
    owner_user_id: str | None = None,
    status: AIAnalysisStatus | None = None,
    task_id: str | None = None,
) -> int:
    stmt = sa.select(sa.func.count()).select_from(AIAnalysisRequestRecord).where(
        *_build_ai_analysis_filters(
            project_id=project_id,
            organization_id=organization_id,
            owner_user_id=owner_user_id,
            status=status,
            task_id=task_id,
        )
    )
    return int((await session.execute(stmt)).scalar_one())


async def update_ai_analysis_request(
    session: AsyncSession,
    *,
    request: AIAnalysisRequestRecord,
    status: AIAnalysisStatus,
    title: str | None = None,
    result: dict[str, Any] | None = None,
    error: str | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
) -> AIAnalysisRequestRecord:
    request.status = status
    if title is not None:
        request.title = title
    if result is not None:
        request.result = result
    if error is not None:
        request.error = error
    if started_at is not None:
        request.started_at = started_at
    if finished_at is not None:
        request.finished_at = finished_at
    await session.flush()
    await session.refresh(request)
    return request
