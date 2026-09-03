from src.exception_registry.exception_types import ExceptionCategory
from src.exception_registry.registered_exception import RegisteredException


class ProjectScheduleNotFoundException(RegisteredException):
    name = "CRUD_PROJECT_SCHEDULE_NOT_FOUND"
    code = "CRUD_PROJECT_SCHEDULE_404"
    description = "Расписание проекта не найдено"
    category = ExceptionCategory.CRUD_PROJECT_SCHEDULE.value


class ProjectScheduleAccessForbiddenException(RegisteredException):
    name = "CRUD_PROJECT_SCHEDULE_ACCESS_FORBIDDEN"
    code = "CRUD_PROJECT_SCHEDULE_403"
    description = "Доступ к расписанию проекта запрещен"
    category = ExceptionCategory.CRUD_PROJECT_SCHEDULE.value
