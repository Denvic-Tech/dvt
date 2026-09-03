from src.exception_registry.exception_types import ExceptionCategory
from src.exception_registry.registered_exception import RegisteredException


class UserNotFoundException(RegisteredException):
    name = "CRUD_USER_NOT_FOUND"
    code = "CRUD_USER_404"
    description = "Пользователь не найден"
    category = ExceptionCategory.CRUD_USER.value


class UserAlreadyExistsException(RegisteredException):
    name = "CRUD_USER_ALREADY_EXISTS"
    code = "CRUD_USER_409"
    description = "Пользователь уже существует"
    category = ExceptionCategory.CRUD_USER.value


class UserActionForbiddenException(RegisteredException):
    name = "CRUD_USER_FORBIDDEN"
    code = "CRUD_USER_403"
    description = "Действие над пользователем запрещено"
    category = ExceptionCategory.CRUD_USER.value