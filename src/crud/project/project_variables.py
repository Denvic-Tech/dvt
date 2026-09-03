from typing import Any, Dict, List, Mapping

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from src.exception_registry.errors_list.gateway import project as project_exc
from src.modules.project.infra.db_models import ProjectRecord
from src.modules.user.infra.db_models import UserRecord
from src.schemas.http.project_variable import (
    ProjectVariableBase,
    ProjectVariableCreate,
    ProjectVariableRead,
    ProjectVariablesBulkUpdate,
    ProjectVariableUpdate,
)
from src.utils.project_variables import normalize_project_variable_storage_payload
from src.utils.user_roles import user_has_admin_access, user_has_global_access


def _check_access(project: ProjectRecord, user: UserRecord) -> None:
    if user_has_global_access(user):
        return
    if project.organization_id != user.organization_id:
        raise project_exc.ProjectAccessForbidden(status_code=status.HTTP_403_FORBIDDEN)
    if not user_has_admin_access(user) and project.user_id != user.id:
        raise project_exc.ProjectAccessForbidden(status_code=status.HTTP_403_FORBIDDEN)


async def _get_project_or_404(db: AsyncSession, project_id: str) -> ProjectRecord:
    project = await db.get(ProjectRecord, project_id)
    if not project:
        raise project_exc.ProjectNotFound(status_code=status.HTTP_404_NOT_FOUND)
    return project


async def get_variables(
    db: AsyncSession,
    project_id: str,
    user: UserRecord,
) -> List[ProjectVariableRead]:
    project = await _get_project_or_404(db, project_id)
    _check_access(project, user)
    variables = project.variables or {}
    return [
        ProjectVariableRead(
            key=key,
            **normalize_project_variable_storage_payload(value, allow_legacy=True),
        )
        for key, value in variables.items()
    ]


async def get_variable(
    db: AsyncSession,
    project_id: str,
    variable_key: str,
    user: UserRecord,
) -> ProjectVariableRead:
    project = await _get_project_or_404(db, project_id)
    _check_access(project, user)

    variables = project.variables or {}
    if variable_key not in variables:
        raise project_exc.ProjectVariableNotFound(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Переменная '{variable_key}' не найдена",
        )

    return ProjectVariableRead(
        key=variable_key,
        **normalize_project_variable_storage_payload(variables[variable_key], allow_legacy=True),
    )


def _normalize_variable_write_payload(
    variable_data: ProjectVariableBase | Mapping[str, Any],
) -> dict[str, Any]:
    if isinstance(variable_data, ProjectVariableBase):
        payload = variable_data.model_dump()
    else:
        payload = dict(variable_data)
    return normalize_project_variable_storage_payload(payload, allow_legacy=False)


async def create_variable(
    db: AsyncSession,
    project_id: str,
    variable_key: str,
    variable_data: ProjectVariableCreate,
    user: UserRecord,
) -> ProjectVariableRead:
    project = await _get_project_or_404(db, project_id)
    _check_access(project, user)

    variables = project.variables or {}
    if variable_key in variables:
        raise project_exc.ProjectVariableAlreadyExists(status_code=status.HTTP_409_CONFLICT)

    normalized_payload = _normalize_variable_write_payload(variable_data)
    variables[variable_key] = normalized_payload
    project.variables = variables
    flag_modified(project, "variables")

    db.add(project)
    await db.commit()
    await db.refresh(project)
    return ProjectVariableRead(key=variable_key, **normalized_payload)


async def update_variable(
    db: AsyncSession,
    project_id: str,
    variable_key: str,
    variable_data: ProjectVariableUpdate,
    user: UserRecord,
) -> ProjectVariableRead:
    project = await _get_project_or_404(db, project_id)
    _check_access(project, user)

    if project.variables is None:
        project.variables = {}

    if variable_key not in project.variables:
        raise project_exc.ProjectVariableNotFound(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Переменная '{variable_key}' не найдена",
        )

    normalized_payload = _normalize_variable_write_payload(variable_data)
    project.variables[variable_key] = normalized_payload
    flag_modified(project, "variables")
    await db.commit()
    await db.refresh(project)
    return ProjectVariableRead(key=variable_key, **normalized_payload)


async def delete_variable(
    db: AsyncSession,
    project_id: str,
    variable_key: str,
    user: UserRecord,
) -> None:
    project = await _get_project_or_404(db, project_id)
    _check_access(project, user)

    variables = project.variables or {}
    if variable_key not in variables:
        raise project_exc.ProjectVariableNotFound(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Переменная '{variable_key}' не найдена",
        )

    del variables[variable_key]
    project.variables = variables
    flag_modified(project, "variables")
    db.add(project)
    await db.commit()


async def bulk_update_variables(
    db: AsyncSession,
    project_id: str,
    bulk_data: ProjectVariablesBulkUpdate,
    user: UserRecord,
) -> List[ProjectVariableRead]:
    project = await _get_project_or_404(db, project_id)
    _check_access(project, user)

    variables = project.variables or {}
    normalized_updates = {
        key: _normalize_variable_write_payload(value)
        for key, value in bulk_data.variables.items()
    }
    variables.update(normalized_updates)
    project.variables = variables
    flag_modified(project, "variables")

    db.add(project)
    await db.commit()
    await db.refresh(project)
    return [
        ProjectVariableRead(key=key, **value)
        for key, value in normalized_updates.items()
    ]


async def set_variables(
    db: AsyncSession,
    project_id: str,
    variables: Dict[str, ProjectVariableBase | Mapping[str, Any]],
    user: UserRecord,
) -> List[ProjectVariableRead]:
    project = await _get_project_or_404(db, project_id)
    _check_access(project, user)

    normalized_variables = {
        key: _normalize_variable_write_payload(value)
        for key, value in variables.items()
    }
    project.variables = normalized_variables
    flag_modified(project, "variables")
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return [
        ProjectVariableRead(key=key, **value)
        for key, value in normalized_variables.items()
    ]

