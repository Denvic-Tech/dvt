from typing import Annotated

from fastapi import Body, Depends, Path, Query
from usrak.core.dependencies.user import build_user_dependency
from usrak.core.enums import AuthMode

from services.gateway.exceptions import project as project_exc

from src.crud import project as project_crud
from src.db.fastapi.dependencies import AsyncSessionDepends
from src.modules.project.infra.db_models import ProjectRecord
from src.modules.user.infra.db_models import UserRecord
from src.modules.user.infra.fastapi.dependencies import UserAccessOnly
from src.utils.access_control import get_access_scope

_get_user_verified_and_active_any = build_user_dependency(
    auth_mode=AuthMode.ANY,
    require_verified=True,
    require_active=True,
)
UserAnyAccess = Annotated[UserRecord, Depends(_get_user_verified_and_active_any)]


ProjectIDFromPath = Annotated[str, Path(description="Project ID")]
ProjectIDFromQuery = Annotated[str, Query(description="Project ID")]
ProjectIDFromBody = Annotated[str, Body(description="Project ID")]


async def get_user_project_by_path(
        project_id: ProjectIDFromPath,
        session: AsyncSessionDepends,
        user: UserAccessOnly,
) -> ProjectRecord:
    """
    Dependency для получения проекта по Path
    """
    access_scope = get_access_scope(user)
    project = (await project_crud.get_projects_by(
        session=session,
        organization_id=access_scope.organization_id,
        owner_user_id=access_scope.owner_user_id,
        project_id=project_id,
    )).first()

    if not project:
        raise project_exc.ProjectNotFoundHTTPError(project_id=project_id)

    return project


async def get_user_project_by_query(
        project_id: ProjectIDFromQuery,
        session: AsyncSessionDepends,
        user: UserAccessOnly,
) -> ProjectRecord:
    """
    Dependency для получения проекта по Query
    """
    access_scope = get_access_scope(user)
    project = (await project_crud.get_projects_by(
        session=session,
        organization_id=access_scope.organization_id,
        owner_user_id=access_scope.owner_user_id,
        project_id=project_id,
    )).first()

    if not project:
        raise project_exc.ProjectNotFoundHTTPError(project_id=project_id)

    return project


async def get_user_project_by_path_any_auth(
        project_id: ProjectIDFromPath,
        session: AsyncSessionDepends,
        user: UserAnyAccess,
) -> ProjectRecord:
    """
    Dependency для получения проекта по Path c поддержкой access token и API key.
    """
    access_scope = get_access_scope(user)
    project = (await project_crud.get_projects_by(
        session=session,
        organization_id=access_scope.organization_id,
        owner_user_id=access_scope.owner_user_id,
        project_id=project_id,
    )).first()

    if not project:
        raise project_exc.ProjectNotFoundHTTPError(project_id=project_id)

    return project


UserProjectByPath = Annotated[ProjectRecord, Depends(get_user_project_by_path)]
UserProjectByQuery = Annotated[ProjectRecord, Depends(get_user_project_by_query)]
UserProjectByPathAnyAuth = Annotated[ProjectRecord, Depends(get_user_project_by_path_any_auth)]
