from src.exception_registry import RegisteredException
from src.exception_registry.exception_types import ExceptionCategory


class ProjectNotFoundException(RegisteredException):
    name = "CRUD_PROJECT_NOT_FOUND"
    code = "CRUD_PROJECT_404"
    description = "Проект не найден"
    category = ExceptionCategory.CRUD_PROJECT.value


class ProjectAccessForbiddenException(RegisteredException):
    name = "CRUD_PROJECT_ACCESS_FORBIDDEN"
    code = "CRUD_PROJECT_403"
    description = "Доступ к проекту запрещен"
    category = ExceptionCategory.CRUD_PROJECT.value


class ProjectVariableNotFoundException(RegisteredException):
    name = "CRUD_PROJECT_VARIABLE_NOT_FOUND"
    code = "CRUD_PROJECT_VARIABLE_404"
    description = "Переменная проекта не найдена"
    category = ExceptionCategory.CRUD_PROJECT.value


class ProjectVariableAlreadyExistsException(RegisteredException):
    name = "CRUD_PROJECT_VARIABLE_ALREADY_EXISTS"
    code = "CRUD_PROJECT_VARIABLE_409"
    description = "Переменная проекта уже существует"
    category = ExceptionCategory.CRUD_PROJECT.value
