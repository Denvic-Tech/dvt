from typing import Annotated

from fastapi import APIRouter, Query

from services.gateway.deps.project import UserProjectByPath
from services.gateway.routes.impl import project as project_impl

from src.db.fastapi.dependencies import AsyncSessionDepends
from src.modules.user.infra.fastapi.dependencies import UserAccessOnly
from src.schemas.http.log import LogEntriesPageSchema

router = APIRouter(prefix="/logs")


@router.get("", response_model=LogEntriesPageSchema)
async def get_project_logs(
        project: UserProjectByPath,
        user: UserAccessOnly,
        session: AsyncSessionDepends,
        task_id: Annotated[str, Query(min_length=1, description="ID задачи")],
        limit: Annotated[int, Query(
            ge=1,
            le=project_impl.PROJECT_LOGS_MAX_LIMIT,
        )] = project_impl.PROJECT_LOGS_DEFAULT_LIMIT,
        offset: Annotated[int, Query(ge=0)] = 0,
) -> LogEntriesPageSchema:
    return await project_impl.get_project_logs_route_impl(
        project=project,
        user=user,
        task_id=task_id,
        limit=limit,
        offset=offset,
        session=session,
    )
