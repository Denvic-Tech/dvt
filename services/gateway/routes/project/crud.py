from typing import Annotated, Literal

from fastapi import APIRouter, Query

from services.gateway.deps.project import UserProjectByPath
from services.gateway.routes.impl import project as project_impl

from src.db.fastapi.dependencies import AsyncSessionDepends
from src.modules.user.infra.fastapi.dependencies import UserAccessOnly
from src.schemas.http.common import CommonResponse
from src.schemas.http.project import (
    ProjectCreateSchema,
    ProjectFolderCreateSchema,
    ProjectFolderReadSchema,
    ProjectFolderUpdateSchema,
    ProjectItemsPageSchema,
    ProjectReadSchema,
    ProjectsDeleteSchema,
    ProjectSearchPageSchema,
    ProjectUpdateSchema,
)

r = router = APIRouter()


@router.get("/items", response_model=ProjectItemsPageSchema)
async def get_project_items(
    session: AsyncSessionDepends,
    user: UserAccessOnly,
    folder_id: Annotated[str | None, Query(description="ID папки, null означает root")] = None,
    organization_id: Annotated[
        str | None,
        Query(
            description="ID организации для выборки элементов в рамках доступного access scope",
        ),
    ] = None,
    limit: Annotated[
        int,
        Query(
            ge=1,
            le=project_impl.PROJECT_ITEMS_MAX_LIMIT,
        ),
    ] = project_impl.PROJECT_ITEMS_DEFAULT_LIMIT,
    offset: Annotated[int, Query(ge=0)] = 0,
    sort_by: Annotated[
        Literal["default", "updated_at"],
        Query(description="Поле серверной сортировки mixed-элементов"),
    ] = "default",
    sort_order: Annotated[
        Literal["asc", "desc"],
        Query(description="Направление серверной сортировки"),
    ] = "desc",
    include_last_runs: Annotated[
        bool, Query(description="Добавить последние запуски проектов")
    ] = True,
) -> ProjectItemsPageSchema:
    return await project_impl.get_project_items_route_impl(
        folder_id=folder_id,
        organization_id=organization_id,
        limit=limit,
        offset=offset,
        sort_by=sort_by,
        sort_order=sort_order,
        include_last_runs=include_last_runs,
        session=session,
        user=user,
    )


@router.post("/folders", response_model=ProjectFolderReadSchema)
async def create_project_folder(
    data: ProjectFolderCreateSchema,
    session: AsyncSessionDepends,
    user: UserAccessOnly,
) -> ProjectFolderReadSchema:
    return await project_impl.create_project_folder_route_impl(
        data=data,
        session=session,
        user=user,
    )


@router.patch("/folders/{folder_id}", response_model=ProjectFolderReadSchema)
async def update_project_folder(
    folder_id: str,
    data: ProjectFolderUpdateSchema,
    session: AsyncSessionDepends,
    user: UserAccessOnly,
) -> ProjectFolderReadSchema:
    return await project_impl.update_project_folder_route_impl(
        folder_id=folder_id,
        data=data,
        session=session,
        user=user,
    )


@router.delete("/folders/{folder_id}", response_model=CommonResponse)
async def delete_project_folder(
    folder_id: str,
    session: AsyncSessionDepends,
    user: UserAccessOnly,
) -> CommonResponse:
    return await project_impl.delete_project_folder_route_impl(
        folder_id=folder_id,
        session=session,
        user=user,
    )


@router.get("/search", response_model=ProjectSearchPageSchema)
async def search_projects(
    session: AsyncSessionDepends,
    user: UserAccessOnly,
    name: Annotated[
        str,
        Query(min_length=1, description="Подстрока для поиска по названию папки или проекта"),
    ],
    item_type: Annotated[
        Literal["all", "folder", "project"], Query(description="Тип искомых элементов")
    ] = "all",
    folder_id: Annotated[str | None, Query(description="ID папки для ограничения поиска")] = None,
    organization_id: Annotated[
        str | None,
        Query(
            description="ID организации для поиска в рамках доступного access scope",
        ),
    ] = None,
    limit: Annotated[
        int,
        Query(
            ge=1,
            le=project_impl.PROJECT_ITEMS_MAX_LIMIT,
        ),
    ] = project_impl.PROJECT_ITEMS_DEFAULT_LIMIT,
    offset: Annotated[int, Query(ge=0)] = 0,
    sort_by: Annotated[
        Literal["default", "updated_at"],
        Query(description="Поле серверной сортировки mixed-элементов"),
    ] = "default",
    sort_order: Annotated[
        Literal["asc", "desc"],
        Query(description="Направление серверной сортировки"),
    ] = "desc",
    include_last_runs: Annotated[
        bool, Query(description="Добавить последние запуски проектов")
    ] = True,
) -> ProjectSearchPageSchema:
    return await project_impl.search_projects_route_impl(
        name=name,
        item_type=item_type,
        folder_id=folder_id,
        organization_id=organization_id,
        limit=limit,
        offset=offset,
        sort_by=sort_by,
        sort_order=sort_order,
        include_last_runs=include_last_runs,
        session=session,
        user=user,
    )


@router.get("", response_model=list[ProjectReadSchema])
async def get_projects(
    session: AsyncSessionDepends,
    user: UserAccessOnly,
    sort_by: Annotated[
        Literal["default", "updated_at"],
        Query(description="Поле серверной сортировки плоского списка проектов"),
    ] = "default",
    sort_order: Annotated[
        Literal["asc", "desc"],
        Query(description="Направление серверной сортировки"),
    ] = "desc",
) -> list[ProjectReadSchema]:
    return await project_impl.get_projects_route_impl(
        session=session,
        user=user,
        sort_by=sort_by,
        sort_order=sort_order,
    )


@router.post("", response_model=ProjectReadSchema)
async def create_project(
    data: ProjectCreateSchema,
    session: AsyncSessionDepends,
    user: UserAccessOnly,
) -> ProjectReadSchema:
    return await project_impl.create_project_route_impl(
        data=data,
        session=session,
        user=user,
    )


@router.get("/{project_id}", response_model=ProjectReadSchema)
async def get_project_by_id(
    project: UserProjectByPath,
    session: AsyncSessionDepends,
    user: UserAccessOnly,
) -> ProjectReadSchema:
    return await project_impl.get_project_by_id_route_impl(
        project=project,
        session=session,
        user=user,
    )


@router.patch("/{project_id}", response_model=ProjectReadSchema)
async def update_project(
    data: ProjectUpdateSchema,
    user: UserAccessOnly,
    session: AsyncSessionDepends,
    project: UserProjectByPath,
) -> ProjectReadSchema:
    return await project_impl.update_project_route_impl(
        data=data,
        session=session,
        user=user,
        project=project,
    )


@router.delete("/batch", response_model=CommonResponse)
async def delete_projects(
    data: ProjectsDeleteSchema,
    session: AsyncSessionDepends,
    user: UserAccessOnly,
) -> CommonResponse:
    return await project_impl.delete_projects_route_impl(
        data=data,
        session=session,
        user=user,
    )


@router.delete("/{project_id}", response_model=CommonResponse)
async def delete_project(
    session: AsyncSessionDepends,
    project: UserProjectByPath,
) -> CommonResponse:
    return await project_impl.delete_project_route_impl(
        session=session,
        project=project,
    )
