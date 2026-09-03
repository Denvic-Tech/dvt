from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Header, Query, Response, status

from services.gateway.deps.project import UserProjectByPath
from services.gateway.routes.impl import ai_analysis as ai_analysis_impl

from src.db.fastapi.dependencies import AsyncSessionDepends
from src.enums import AIAnalysisStatus
from src.modules.user.infra.fastapi.dependencies import UserAccessOnly
from src.schemas.http.ai_analysis import (
    AIAnalysisCreateResponseSchema,
    AIAnalysisCreateSchema,
    AIAnalysisHistoryResponseSchema,
    AIAnalysisReadSchema,
)

router = APIRouter(prefix="/ai", tags=["AI Analysis"])


@router.post(
    "/analyze",
    response_model=AIAnalysisCreateResponseSchema,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_ai_analysis_request(
    session: AsyncSessionDepends,
    user: UserAccessOnly,
    project: UserProjectByPath,
    data: AIAnalysisCreateSchema,
    background_tasks: BackgroundTasks,
    response: Response,
    accept_language: Annotated[str | None, Header(alias="Accept-Language")] = None,
) -> AIAnalysisCreateResponseSchema:
    payload = await ai_analysis_impl.create_ai_analysis_request_route_impl(
        session=session,
        user=user,
        project=project,
        data=data,
        accept_language=accept_language,
    )
    response.headers["Retry-After"] = ai_analysis_impl.RETRY_AFTER_SECONDS
    background_tasks.add_task(ai_analysis_impl.run_ai_analysis_request, payload.request_id)
    return payload


@router.get("/analyze", response_model=AIAnalysisHistoryResponseSchema)
async def list_ai_analysis_requests(
    session: AsyncSessionDepends,
    user: UserAccessOnly,
    project: UserProjectByPath,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    request_status: Annotated[AIAnalysisStatus | None, Query(alias="status")] = None,
    task_id: Annotated[str | None, Query()] = None,
) -> AIAnalysisHistoryResponseSchema:
    return await ai_analysis_impl.list_ai_analysis_requests_route_impl(
        session=session,
        user=user,
        project=project,
        limit=limit,
        offset=offset,
        request_status=request_status,
        task_id=task_id,
    )


@router.get("/analyze/{request_id}", response_model=AIAnalysisReadSchema)
async def get_ai_analysis_request(
    request_id: str,
    response: Response,
    session: AsyncSessionDepends,
    user: UserAccessOnly,
    project: UserProjectByPath,
) -> AIAnalysisReadSchema:
    payload = await ai_analysis_impl.get_ai_analysis_request_route_impl(
        session=session,
        user=user,
        project=project,
        request_id=request_id,
    )
    if payload.status in {AIAnalysisStatus.QUEUED, AIAnalysisStatus.RUNNING}:
        response.headers["Retry-After"] = ai_analysis_impl.RETRY_AFTER_SECONDS
    return payload
