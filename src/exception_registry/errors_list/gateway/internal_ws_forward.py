from src.exception_registry.exception_types import ExceptionCategory
from src.exception_registry.registered_exception import RegisteredHTTPException


class WSForwardHTTPExceptionNotFound(RegisteredHTTPException):
    name = 'WS_FORWARD_PROJECT_NOT_FOUND'
    code = 'GATEWAY_EXCEPTION_404'
    description = 'Проект не найден'
    category = ExceptionCategory.SERVICE_GATEWAY_INTERNAL.value