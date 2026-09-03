import asyncio

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.clients.ai_analysis_client import (
    create_remote_analysis_request,
    get_remote_analysis_request,
    get_remote_analysis_requests,
)
from src.crud import ai_analysis as ai_analysis_crud, project as project_crud
from src.db.session import get_async_session_acm
from src.enums import AIAnalysisStatus
from src.logger import logger
from src.models import AIAnalysisRequestRecord
from src.modules.project.infra.db_models import ProjectRecord
from src.modules.task_execution.domain.types import TaskExecutionStatus
from src.modules.task_execution.infra.queries import get_accessible_task
from src.modules.user.infra.db_models import UserRecord
from src.pipeline.execution_mode import PipelineExecutionMode
from src.schemas.http.ai_analysis import (
    AIAnalysisCreateResponseSchema,
    AIAnalysisCreateSchema,
    AIAnalysisHistoryResponseSchema,
    AIAnalysisReadSchema,
)
from src.utils.access_control import get_access_scope

import config

from .mappers import (
    NON_TERMINAL_STATUSES,
    apply_remote_payload,
    is_terminal_status,
    map_remote_status,
    request_to_history_item,
    request_to_read_schema,
    utcnow,
)
from .payloads import build_remote_request_payload

RETRY_AFTER_SECONDS = "2"
_BACKGROUND_SYNC_MAX_POLLS = 2


def _ensure_ai_analysis_enabled() -> None:
    if not config.AI_ANALYSIS.ENABLED:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Feature disabled",
        )


async def _sync_remote_analysis_request(
    session: AsyncSession,
    *,
    request: AIAnalysisRequestRecord,
    remote_request_id: str,
) -> AIAnalysisRequestRecord:
    remote_payload = await get_remote_analysis_request(remote_request_id)
    return await apply_remote_payload(session, request=request, remote_payload=remote_payload)


def _get_refreshable_requests(
    requests: list[AIAnalysisRequestRecord],
) -> list[tuple[AIAnalysisRequestRecord, str]]:
    refreshable: list[tuple[AIAnalysisRequestRecord, str]] = []
    for request in requests:
        remote_request_id = str(request.ai_service_request_id or "").strip()
        if request.status in NON_TERMINAL_STATUSES and remote_request_id:
            refreshable.append((request, remote_request_id))
    return refreshable


async def _refresh_request_if_needed(
    session: AsyncSession,
    *,
    request: AIAnalysisRequestRecord,
) -> bool:
    refreshable = _get_refreshable_requests([request])
    if not refreshable:
        return False

    _, remote_request_id = refreshable[0]
    await _sync_remote_analysis_request(
        session,
        request=request,
        remote_request_id=remote_request_id,
    )
    await session.commit()
    return True


async def _refresh_requests_best_effort(
    session: AsyncSession,
    *,
    requests: list[AIAnalysisRequestRecord],
) -> bool:
    refreshable = _get_refreshable_requests(requests)
    if not refreshable:
        return False

    try:
        remote_batch_payload = await get_remote_analysis_requests(
            [remote_request_id for _, remote_request_id in refreshable]
        )
    except Exception:
        logger.exception("Failed to refresh AI analysis request page from AI service")
        return False

    remote_payloads = {
        item.request_id: item.request
        for item in remote_batch_payload.items
        if item.found and item.request is not None
    }

    any_refreshed = False
    for request, remote_request_id in refreshable:
        remote_payload = remote_payloads.get(remote_request_id)
        if remote_payload is None:
            continue

        try:
            await apply_remote_payload(session, request=request, remote_payload=remote_payload)
            await session.commit()
            refreshed = True
        except Exception:
            logger.exception(f"Failed to refresh AI analysis request {request.id} from AI service")
            continue

        any_refreshed = any_refreshed or refreshed

    return any_refreshed


async def _perform_background_sync_attempts(
    session: AsyncSession,
    *,
    request: AIAnalysisRequestRecord,
    remote_request_id: str,
) -> None:
    for attempt in range(_BACKGROUND_SYNC_MAX_POLLS):
        await _sync_remote_analysis_request(
            session,
            request=request,
            remote_request_id=remote_request_id,
        )
        await session.commit()

        if is_terminal_status(request.status):
            return

        if attempt < _BACKGROUND_SYNC_MAX_POLLS - 1:
            await asyncio.sleep(config.AI_ANALYSIS.STATUS_POLL_INTERVAL_SEC)


async def create_ai_analysis_request_route_impl(
    *,
    session: AsyncSession,
    user: UserRecord,
    project: ProjectRecord,
    data: AIAnalysisCreateSchema,
    accept_language: str | None,
) -> AIAnalysisCreateResponseSchema:
    del accept_language
    # TODO: удаляем accept_language до внедрения локализации (если нужно)
    _ensure_ai_analysis_enabled()
    access_scope = get_access_scope(user)

    task = await get_accessible_task(
        session=session,
        organization_id=access_scope.organization_id,
        owner_user_id=access_scope.owner_user_id,
        project_id=project.id,
        task_id=data.task_id,
    )
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task ID={data.task_id} not found.",
        )
    if task.status != TaskExecutionStatus.ERROR:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="AI analysis is available only for failed tasks.",
        )
    if task.mode != PipelineExecutionMode.FULL:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="AI analysis is available only for full project runs.",
        )

    request = await ai_analysis_crud.create_ai_analysis_request(
        session,
        task_id=task.task_id,
        project_id=project.id,
        user_id=task.user_id,
        organization_id=project.organization_id,
    )
    await session.commit()
    await session.refresh(request)
    return AIAnalysisCreateResponseSchema(request_id=request.id, status=request.status)


async def get_ai_analysis_request_route_impl(
    *,
    session: AsyncSession,
    user: UserRecord,
    project: ProjectRecord,
    request_id: str,
) -> AIAnalysisReadSchema:
    _ensure_ai_analysis_enabled()
    access_scope = get_access_scope(user)
    request = await ai_analysis_crud.get_ai_analysis_request_by_id(
        session,
        request_id=request_id,
        project_id=project.id,
        organization_id=access_scope.organization_id,
        owner_user_id=access_scope.owner_user_id,
    )
    if request is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI analysis not found.")

    try:
        await _refresh_request_if_needed(session, request=request)
    except Exception:
        logger.exception(f"Failed to refresh AI analysis request {request.id} from AI service")

    return request_to_read_schema(request)


async def list_ai_analysis_requests_route_impl(
    *,
    session: AsyncSession,
    user: UserRecord,
    project: ProjectRecord,
    limit: int,
    offset: int,
    request_status: AIAnalysisStatus | None,
    task_id: str | None,
) -> AIAnalysisHistoryResponseSchema:
    _ensure_ai_analysis_enabled()
    access_scope = get_access_scope(user)
    items = await ai_analysis_crud.list_ai_analysis_requests(
        session,
        project_id=project.id,
        organization_id=access_scope.organization_id,
        owner_user_id=access_scope.owner_user_id,
        status=request_status,
        task_id=task_id,
        limit=limit,
        offset=offset,
    )

    await _refresh_requests_best_effort(session, requests=items)

    items = await ai_analysis_crud.list_ai_analysis_requests(
        session,
        project_id=project.id,
        organization_id=access_scope.organization_id,
        owner_user_id=access_scope.owner_user_id,
        status=request_status,
        task_id=task_id,
        limit=limit,
        offset=offset,
    )
    total = await ai_analysis_crud.count_ai_analysis_requests(
        session,
        project_id=project.id,
        organization_id=access_scope.organization_id,
        owner_user_id=access_scope.owner_user_id,
        status=request_status,
        task_id=task_id,
    )
    return AIAnalysisHistoryResponseSchema(
        items=[request_to_history_item(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


async def run_ai_analysis_request(request_id: str) -> None:
    if not config.AI_ANALYSIS.ENABLED:
        logger.warning(f"Skip AI analysis request {request_id}: feature is disabled")
        return

    async with get_async_session_acm() as session:
        request = await ai_analysis_crud.get_ai_analysis_request_by_id(
            session,
            request_id=request_id,
        )
        if request is None or is_terminal_status(request.status):
            return

        remote_request_id = request.ai_service_request_id
        try:
            request.started_at = request.started_at or utcnow()
            await session.flush()
            await session.commit()

            if remote_request_id:
                try:
                    await _perform_background_sync_attempts(
                        session,
                        request=request,
                        remote_request_id=remote_request_id,
                    )
                except Exception:
                    logger.exception(
                        f"Background sync failed for AI analysis request {request_id}"
                    )
                return

            project = (
                await project_crud.get_projects_by(
                    session=session,
                    organization_id=request.organization_id,
                    project_id=request.project_id,
                )
            ).first()
            if project is None:
                raise RuntimeError(f"Project ID={request.project_id} not found")

            remote_payload = await build_remote_request_payload(session, request, project)
            remote_create_payload = await create_remote_analysis_request(remote_payload)
            remote_request_id = remote_create_payload.request_id
            if not remote_request_id:
                raise RuntimeError("AI service create response does not contain request_id")

            request.ai_service_request_id = remote_request_id
            remote_status, default_error = map_remote_status(remote_create_payload.status)
            request.status = remote_status
            if default_error is not None:
                request.error = default_error
                request.finished_at = utcnow()

            await session.flush()
            await session.commit()

            try:
                await _perform_background_sync_attempts(
                    session,
                    request=request,
                    remote_request_id=remote_request_id,
                )
            except Exception:
                logger.exception(
                    f"Background sync failed for AI analysis request {request_id}"
                )
        except Exception as exc:
            logger.exception(f"AI analysis request {request_id} failed")
            await ai_analysis_crud.update_ai_analysis_request(
                session,
                request=request,
                status=AIAnalysisStatus.ERROR,
                error=str(exc),
                finished_at=utcnow(),
            )
            await session.commit()
