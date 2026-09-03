from src.exception_registry.exception_types import ExceptionCategory
from src.exception_registry.registered_exception import RegisteredHTTPException


class ExceptionRegistryNotFound(RegisteredHTTPException):
    name = 'REGISTRY_NOT_FOUND'
    code = 'EXCEPTION_404'
    description = 'Exception не найден'
    category = ExceptionCategory.SERVICE_GATEWAY_EXCEPTION_REGISTRY.value


class ExceptionRegistryValidationError(RegisteredHTTPException):
    name = 'REGISTRY_VALIDATION_ERROR'
    code = 'EXCEPTION_400'
    description = 'Ошибка при создании и регистрации Exception'
    category = ExceptionCategory.SERVICE_GATEWAY_EXCEPTION_REGISTRY.value