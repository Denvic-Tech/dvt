from src.exception_registry.exception_types import ExceptionCategory
from src.exception_registry.registered_exception import RegisteredHTTPException


class ConnectionNotFound(RegisteredHTTPException):
    name = "CONNECTION_NOT_FOUND"
    code = "CONNECTION_404"
    description = "Connection not found"
    category = ExceptionCategory.SERVICE_GATEWAY_STORAGE.value