from fastapi import APIRouter

from services.gateway.deps.project import UserProjectByPath
from services.gateway.routes.impl import project as project_impl

from src.db.fastapi.dependencies import AsyncSessionDepends
from src.modules.user.infra.fastapi.dependencies import UserAccessOnly
from src.schemas.http.common import CommonResponse
from src.schemas.http.project import ProjectReadSchema

r = router = APIRouter()


@router.get(
    "/favorites",
    response_model=list[ProjectReadSchema],
    summary="Получить избранные проекты текущего пользователя",
)
async def get_favorite_projects(
    session: AsyncSessionDepends,
    user: UserAccessOnly,
) -> list[ProjectReadSchema]:
    return await project_impl.get_favorite_projects_route_impl(
        session=session,
        user=user,
    )


@router.put(
    "/{project_id}/favorite",
    response_model=CommonResponse,
    summary="Добавить проект в избранное",
)
async def add_favorite_project(
    session: AsyncSessionDepends,
    user: UserAccessOnly,
    project: UserProjectByPath,
) -> CommonResponse:
    return await project_impl.add_favorite_project_route_impl(
        session=session,
        user=user,
        project=project,
    )


@router.delete(
    "/{project_id}/favorite",
    response_model=CommonResponse,
    summary="Убрать проект из избранного",
)
async def remove_favorite_project(
    session: AsyncSessionDepends,
    user: UserAccessOnly,
    project: UserProjectByPath,
) -> CommonResponse:
    return await project_impl.remove_favorite_project_route_impl(
        session=session,
        user=user,
        project=project,
    )
