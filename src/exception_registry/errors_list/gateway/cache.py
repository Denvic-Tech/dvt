from src.exception_registry.exception_types import ExceptionCategory
from src.exception_registry.registered_exception import RegisteredHTTPException


class CacheEntriesNotFound(RegisteredHTTPException):
    name = "CACHE_ENTRIES_NOT_FOUND"
    code = "CACHE_ENTRIES_404"
    description = "No cache entries found"
    category = ExceptionCategory.SERVICE_GATEWAY_CACHE.value
