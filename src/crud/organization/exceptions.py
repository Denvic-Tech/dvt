from src.exception_registry.exception_types import ExceptionCategory
from src.exception_registry.registered_exception import RegisteredException


class OrganizationNotFoundException(RegisteredException):
    name = "CRUD_ORGANIZATION_NOT_FOUND"
    code = "CRUD_ORGANIZATION_404"
    description = "Организация не найдена"
    category = ExceptionCategory.CRUD_ORGANIZATION.value


class OrganizationINNConflictException(RegisteredException):
    name = "CRUD_ORGANIZATION_INN_CONFLICT"
    code = "CRUD_ORGANIZATION_409"
    description = "Организация с таким ИНН уже существует"
    category = ExceptionCategory.CRUD_ORGANIZATION.value
