from src.exception_registry.exception_types import ExceptionCategory
from src.exception_registry.registered_exception import RegisteredException


class TaskNotFoundException(RegisteredException):
    name = "TASK_NOT_FOUND"
    code = "TASK_404"
    description = "Задача не найдена"
    category = ExceptionCategory.TASK.value


class InvalidTaskStatusTransition(RegisteredException):
    name = "INVALID_TASK_STATUS_TRANSITION"
    code = "TASK_409"
    description = "Переход между статусами задачи недопустим"
    category = ExceptionCategory.TASK.value
