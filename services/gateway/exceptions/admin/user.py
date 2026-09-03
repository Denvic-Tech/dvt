from http import HTTPStatus

from src.crud.admin import user as admin_user_crud
from src.exception_registry import RegisteredHTTPException


class UserAlreadyExistsHTTPError(RegisteredHTTPException, admin_user_crud.UserAlreadyExistsException):
    status_code = HTTPStatus.CONFLICT

    def __init__(self, email: str | None = None):
        detail = None

        if email:
            detail = f'User email "{email}" already exists'

        super().__init__(detail=detail)


class UserNotFoundHTTPError(RegisteredHTTPException, admin_user_crud.UserNotFoundException):
    status_code = HTTPStatus.NOT_FOUND

    def __init__(self, user_id: str | None = None):
        detail = None

        if user_id:
            detail = f'User {user_id} not found'

        super().__init__(detail=detail)


class UserActionForbiddenHTTPError(RegisteredHTTPException, admin_user_crud.UserActionForbiddenException):
    status_code = HTTPStatus.FORBIDDEN

    def __init__(self, detail: str | None = None):
        super().__init__(detail=detail)
