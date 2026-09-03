from fastapi import APIRouter, status

from src.crud.project.project_variables import (
    bulk_update_variables,
    create_variable,
    delete_variable,
    get_variable,
    get_variables,
    set_variables,
    update_variable,
)
from src.db.fastapi.dependencies import AsyncSessionDepends
from src.modules.user.infra.fastapi.dependencies import UserAccessOnly
from src.schemas.http.project_variable import (
    ProjectVariableBase,
    ProjectVariableCreate,
    ProjectVariableRead,
    ProjectVariablesBulkUpdate,
    ProjectVariableUpdate,
)

router = APIRouter()


@router.get("/", response_model=list[ProjectVariableRead])
async def get_project_variables(
    project_id: str,
    session: AsyncSessionDepends,
    current_user: UserAccessOnly
):
    """Получить все переменные проекта"""
    return await get_variables(session, project_id, current_user)


@router.get("/{variable_key}", response_model=ProjectVariableRead)
async def get_project_variable(
    project_id: str,
    variable_key: str,
    session: AsyncSessionDepends,
    current_user: UserAccessOnly
):
    """Получить конкретную переменную проекта"""
    return await get_variable(session, project_id, variable_key, current_user)


@router.post(
    "/{variable_key}",
    response_model=ProjectVariableRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_project_variable(
    project_id: str,
    variable_key: str,
    variable_data: ProjectVariableCreate,
    session: AsyncSessionDepends,
    current_user: UserAccessOnly
):
    """Создать новую переменную в проекте"""
    return await create_variable(
        session, project_id, variable_key, variable_data, current_user
    )


@router.put("/{variable_key}", response_model=ProjectVariableRead)
async def update_project_variable(
    project_id: str,
    variable_key: str,
    variable_data: ProjectVariableUpdate,
    session: AsyncSessionDepends,
    current_user: UserAccessOnly
):
    """Обновить переменную проекта"""
    return await update_variable(
        session, project_id, variable_key, variable_data, current_user
    )


@router.delete("/{variable_key}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project_variable(
    project_id: str,
    variable_key: str,
    session: AsyncSessionDepends,
    current_user: UserAccessOnly
):
    """Удалить переменную из проекта"""
    await delete_variable(session, project_id, variable_key, current_user)


@router.post("/bulk/update", response_model=list[ProjectVariableRead])
async def bulk_update_project_variables(
    project_id: str,
    bulk_data: ProjectVariablesBulkUpdate,
    session: AsyncSessionDepends,
    current_user: UserAccessOnly
):
    """Массовое обновление переменных проекта"""
    return await bulk_update_variables(
        session, project_id, bulk_data, current_user
    )


@router.put("/", response_model=list[ProjectVariableRead])
async def set_project_variables(
    project_id: str,
    variables: dict[str, ProjectVariableBase],
    session: AsyncSessionDepends,
    current_user: UserAccessOnly
):
    """Полная замена всех переменных проекта"""
    return await set_variables(
        session, project_id, variables, current_user
    )
