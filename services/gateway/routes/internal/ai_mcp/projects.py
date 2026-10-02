from fastapi import HTTPException

from services.gateway.routes.impl.project.crud import create_project_route_impl

from src.modules.ai_mcp_access.domain.types import ResourceScopeMode
from src.schemas.http.project import ProjectCreateSchema

from .auth import MCPPrincipal
from .context import get_project
from .errors import AIMCPHTTPError


async def create_project(
    *, session, principal: MCPPrincipal, name: str, folder_id: str | None = None,
) -> dict:
    if principal.token.access_scope.projects.mode is not ResourceScopeMode.ALL:
        raise AIMCPHTTPError(
            403, "SCOPE_DENIED", "Creating projects requires projects.mode=all.",
        )
    if not isinstance(name, str) or not name.strip():
        raise AIMCPHTTPError(422, "INVALID_ARGUMENTS", "Project name must not be empty.")
    try:
        project = await create_project_route_impl(
            data=ProjectCreateSchema(name=name.strip(), folder_id=folder_id),
            session=session,
            user=principal.user,
        )
    except HTTPException as exc:
        if exc.status_code in {403, 404}:
            raise AIMCPHTTPError(
                404, "FOLDER_NOT_FOUND_OR_DENIED", "Folder was not found or is not accessible.",
            ) from exc
        if exc.status_code in {400, 422}:
            raise AIMCPHTTPError(
                422, "INVALID_ARGUMENTS", "Project settings are invalid.",
            ) from exc
        raise
    return await get_project(session=session, principal=principal, project_id=project.id)
