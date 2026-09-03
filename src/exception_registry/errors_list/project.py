from src.exception_registry.exception_types import ExceptionCategory
from src.exception_registry.registered_exception import RegisteredException


class ProjectNotFoundException(RegisteredException):
    name = "PROJECT_NOT_FOUND"
    code = "PROJECT_404"
    description = "Проект не найден"
    category = ExceptionCategory.PROJECT.value
