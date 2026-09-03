from http import HTTPStatus

from src.crud import project as project_crud
from src.exception_registry import RegisteredHTTPException


class ProjectNotFoundHTTPError(RegisteredHTTPException, project_crud.ProjectNotFoundException):
    status_code = HTTPStatus.NOT_FOUND

    def __init__(self, project_id: str | None = None):
        detail = None

        if project_id:
            detail = f'Project with ID "{project_id}" not found'

        super().__init__(detail=detail)


class ProjectAccessForbiddenHTTPError(RegisteredHTTPException, project_crud.ProjectAccessForbiddenException):
    status_code = HTTPStatus.FORBIDDEN

    def __init__(self, project_id: str | None = None):
        detail = None
        if project_id:
            detail = f'Project with ID "{project_id}" access forbidden'

        super().__init__(detail=detail)


class ProjectVariableNotFoundHTTPError(RegisteredHTTPException, project_crud.ProjectVariableNotFoundException):
    status_code = HTTPStatus.NOT_FOUND

    def __init__(self, project_id: str | None = None):
        detail = None

        if project_id:
            detail = f'Variable for project with ID "{project_id}" not found'

        super().__init__(detail=detail)



class ProjectVariableAlreadyExistsHTTPError(RegisteredHTTPException, project_crud.ProjectVariableAlreadyExistsException):
    status_code = HTTPStatus.CONFLICT

    def __init__(self, project_id: str | None = None):
        detail = None

        if project_id:
            detail = f'Variable for project with ID "{project_id}" already exists'

        super().__init__(detail=detail)