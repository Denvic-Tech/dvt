from http import HTTPStatus

from src.crud import organization as org_crud
from src.exception_registry.exception_types import ExceptionCategory
from src.exception_registry.registered_exception import RegisteredHTTPException


class OrganizationNotFoundHTTPError(org_crud.OrganizationNotFoundException, RegisteredHTTPException):
    status_code = HTTPStatus.NOT_FOUND
    detail = "Organization Not Found"


class OrganizationINNConflictHTTPError(org_crud.OrganizationINNConflictException, RegisteredHTTPException):
    status_code = HTTPStatus.CONFLICT
    detail = "Organization INN Conflict"


class OrganizationForbiddenHttpError(RegisteredHTTPException):
    name = "CRUD_ORGANIZATION_FORBIDDEN"
    code = "CRUD_ORGANIZATION_403"
    description = "Действие над организацией запрещено"
    category = ExceptionCategory.CRUD_ORGANIZATION.value
    status_code = HTTPStatus.FORBIDDEN


class OrganizationInvalidINNHTTPError(RegisteredHTTPException):
    name = "CRUD_ORGANIZATION_INN_INVALID"
    code = "CRUD_ORGANIZATION_400"
    description = "Некорректный ИНН организации"
    category = ExceptionCategory.CRUD_ORGANIZATION.value
    status_code = HTTPStatus.BAD_REQUEST
