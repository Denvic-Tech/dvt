from typing import List, Optional

from fastapi import HTTPException, status

from src.exception_registry.exception_types import ExceptionCategory, ExceptionType
from src.exception_registry.registered_exception import RegisteredHTTPException
from src.exception_registry.utils import register_http_exception, register_custom_exception


class SkipBackgroundRun(Exception):
    """Сигнал: запуск задачи нужно пропустить (например, не взяли lock)."""
    pass


@register_http_exception("DATAFRAME",
                         "DATAFRAME_404",
                         "DataFrame не найден",
                         ExceptionCategory.DATAFRAME.value)
class DataFrameNotFoundError(HTTPException):
    """Исключение: DataFrame не найден."""

    def __init__(self):
        super().__init__(status_code=404, detail="DataFrame not found")


@register_http_exception("DATABASE",
                         'DATABASE_CONNECTION_404',
                         "DB подключение не найдено",
                         ExceptionCategory.DB.value)
class DBEngineNotFoundError(HTTPException):
    """Исключение: DB подключение не найдено."""

    def __init__(self):
        super().__init__(status_code=404, detail="DB engine not found")


@register_custom_exception('GRAPH', 'CYCLE_ERROR', 'Обнаружен цикл зависимостей в графе.')
class DependencyCycleError(Exception):
    """Ошибка: обнаружен цикл зависимостей в графе."""
    pass


@register_custom_exception("NODE_ERROR", "INPUT_ERROR", "Проблема с входом узла")
class NodeInputError(Exception):
    """Ошибка: проблема с входом узла (например, не ссылка, когда ожидается)."""
    pass


@register_custom_exception("NODE_ERROR", "NOT_FOUND", "Узел с указанным ID не найден")
class NodeNotFoundError(Exception):
    """Ошибка: узел с указанным ID не найден."""
    pass


@register_http_exception("USER_AUTH",
                         'INVALID_CREDENTIALS',
                         "Некорректные данные для входа",
                         ExceptionCategory.SERVICE_GATEWAY_TASK.value)
class InvalidCredentialsException(HTTPException):
    def __init__(self):
        super().__init__(
            status_code=403,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


@register_http_exception("BAD_PIPELINE",
                         'PIPELINE_400',
                         "Ошибка при валидации пайплайна",
                         ExceptionCategory.SERVICE_GATEWAY_TASK.value)
class BadPipelineException(HTTPException):
    pass


@register_custom_exception("DUPLICATE_PIPELINE",
                           'PIPELINE_400',
                           "Дублированный пайплайн",
                           ExceptionCategory.SERVICE_GATEWAY_TASK.value)
class DuplicatePipelineException(Exception):
    pass


@register_http_exception("PROJECT_NOT_FOUND", 'NOT_FOUND', "Проект не найден",
                         ExceptionCategory.SERVICE_GATEWAY_PROJECT.value)
class ProjectNotFoundException(HTTPException):
    def __init__(self, project_id: str):
        super().__init__(
            status_code=404,
            detail=f"Project with ID {project_id} not found"
        )


class ProjectsNotFoundException(RegisteredHTTPException):
    name = "PROJECTS_NOT_FOUND"
    code = "NOT_FOUND"
    description = "Проект не найден"
    category = ExceptionCategory.SERVICE_GATEWAY_PROJECT.value
    status_code = status.HTTP_404_NOT_FOUND

    def __init__(self, project_ids: Optional[List[str]] = None):
        if project_ids:
            detail = f"Projects with IDs {', '.join(project_ids)} not found"
        else:
            detail = "Projects not found"

        super().__init__(detail=detail)


@register_http_exception("DATABASE",
                         "VIOLATION_ERROR",
                         "При запросе нарушена ссылочная целостность",
                         ExceptionCategory.DB.value)
class ForeignKeyViolationError(HTTPException):
    def __init__(self, detail: str):
        super().__init__(
            status_code=404,
            detail=detail
        )


@register_http_exception("DATABASE",
                         "TABLE_ALREADY_EXISTS",
                         "Таблица уже создана",
                         ExceptionCategory.DB.value)
class TableAlreadyExistsException(HTTPException):
    def __init__(self, detail: str):
        super().__init__(
            status_code=404,
            detail=detail
        )


@register_http_exception("DATABASE",
                         "VIOLATION_ERROR",
                         "При запросе нарушена уникальность данных по ключам",
                         ExceptionCategory.DB.value)
class UniqueViolationError(HTTPException):
    def __init__(self, detail: str):
        super().__init__(
            status_code=400,
            detail=detail
        )


@register_http_exception("GRAPH_NODE_NOT_FOUND", 'NOT_FOUND',
                         "Некоторые ноды не были найдены, или доступ ограничен",
                         ExceptionCategory.SERVICE_GATEWAY_PROJECT.value)
class GraphNodeNotFoundError(HTTPException):
    def __init__(self, node_ids: List[str]):
        super().__init__(
            status_code=404,
            detail={
                "error": "GraphNodeNotFound",
                "message": "Some GraphNodes were not found or access denied",
                "node_ids": node_ids
            }
        )


@register_custom_exception("S3_CONFIGURATION",
                           "S3_ERROR",
                           "Ошибка в конфигурации S3", ExceptionCategory.S3.value)
class S3ConfigurationError(Exception):
    """Ошибка: неправильная конфигурация S3."""
    pass


class ProjectAndWorkerNotFoundException(RegisteredHTTPException):
    name = 'PROJECT_AND_WORKER_NOT_FOUND'
    code = 'PROJECT_404'
    description = 'Проект и ссылка на worker не найдены в БД'
    category = ExceptionCategory.DB.value


@register_custom_exception("STORAGE_CLIENT_ERROR",
                           "CLIENT_ERROR",
                           "Клиентская ошибка", ExceptionCategory.SERVICE_GATEWAY_STORAGE.value)
class StorageClientError(HTTPException):
    pass


@register_custom_exception("STORAGE_CONFIGURATION_ERROR",
                           "CONFIGURATION_ERROR",
                           "Ошибка в конфигурации для S3",
                           ExceptionCategory.SERVICE_GATEWAY_STORAGE.value)
class StorageS3Error(HTTPException):
    pass


@register_custom_exception("TASK_SERVICE",
                           "FAILED_ACTION",
                           "Ошибка при выполнении действия",
                           ExceptionCategory.SERVICE_GATEWAY_TASK.value)
class FailedProcessTaskException(HTTPException):
    pass


@register_custom_exception("TASK_SERVICE",
                           "UNSUPPORTED_ACTION_400",
                           "Ошибка при выполнении запроса, невалидное действие",
                           ExceptionCategory.SERVICE_GATEWAY_TASK.value)
class UnsupportedActionException(HTTPException):
    pass


@register_http_exception("CACHE_ENTRY_BY_INDEX",
                         "NOT_FOUND",
                         "Cache entry not found",
                         ExceptionCategory.SERVICE_TASK_WORKER_CACHE.value)
class CacheEntryByIndexNotFoundException(HTTPException):
    pass


@register_http_exception("CACHE_ENTRY_BY_KEY",
                         "NOT_FOUND",
                         "Cache entry not found",
                         ExceptionCategory.SERVICE_TASK_WORKER_CACHE.value)
class CacheEntryByKeyNotFoundException(HTTPException):
    pass


@register_http_exception("TASK_NOT_FOUND",
                         "NOT_FOUND",
                         "Задача не найдена",
                         ExceptionCategory.SERVICE_TASK_WORKER_TASKS.value)
class TaskNotFoundException(HTTPException):
    pass


@register_http_exception("WORKER_CLIENT",
                         "CONNECTION_ERROR",
                         "Ошибка при соединении Worker Client",
                         ExceptionCategory.WORKER_CLIENT.value)
class WorkerClientConnectionException(HTTPException):
    pass


@register_http_exception("WORKER_CLIENT",
                         "CLIENT_ERROR",
                         "Клиентская ошибка Worker Client",
                         ExceptionCategory.WORKER_CLIENT.value)
class WorkerClientException(HTTPException):
    pass


class UserNotFoundException(HTTPException):
    def __init__(self, detail: str = "User not found"):
        super().__init__(status_code=404, detail=detail)


class HTTPRequestTimeout(RegisteredHTTPException):
    name = 'HTTP_REQUEST_TIMEOUT'
    code = 'TIMEOUT'
    description = 'Истекло время подключения'
    category = ExceptionCategory.SERVICE_TASK_WORKER_TASKS.value


class HTTPRequestServiceUnavailable(RegisteredHTTPException):
    name = 'HTTP_REQUEST_SERVICE_UNAVAILABLE'
    code = 'SERVICE_UNAVAILABLE'
    description = 'Сервис недоступен'
    category = ExceptionCategory.SERVICE_TASK_WORKER_TASKS.value


class HTTPRequestBadRequest(RegisteredHTTPException):
    name = 'HTTP_REQUEST_BAD_REQUEST'
    code = 'BAD_REQUEST'
    description = 'Ошибка запроса'
    category = ExceptionCategory.SERVICE_TASK_WORKER_TASKS.value


class TaskNotFound(RegisteredHTTPException):
    name = 'TASK_NOT_FOUND'
    code = 'NOT_FOUND'
    description = 'Задача не найдена'
    category = ExceptionCategory.SERVICE_PROJECT_SCHEDULER_TASKS.value

    def __init__(
            self,
            task_id: Optional[str] = None,
            task_name: Optional[str] = None,
    ):
        detail_list = []

        if task_id is not None:
            detail_list.append(f"ID={task_id}")

        if task_name is not None:
            detail_list.append(f"Name={task_name}")

        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task {' '.join(detail_list)} not found"
        )


class TaskAlreadyScheduled(RegisteredHTTPException):
    name = 'TASK_ALREADY_SCHEDULED'
    code = 'ALREADY_SCHEDULED'
    description = 'Задача уже запланирована'
    category = ExceptionCategory.SERVICE_PROJECT_SCHEDULER_TASKS.value

    def __init__(
            self,
            task_id: Optional[str] = None,
            task_name: Optional[str] = None,
    ):
        detail_list = []

        if task_id is not None:
            detail_list.append(f"ID={task_id}")

        if task_name is not None:
            detail_list.append(f"Name={task_name}")

        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Task {' '.join(detail_list)} already scheduled"
        )
    

class TaskAlreadyRunning(RegisteredHTTPException):
    name = 'TASK_ALREADY_RUNNING'
    code = 'ALREADY_RUNNING'
    description = 'Задача уже запущена'
    category = ExceptionCategory.SERVICE_PROJECT_SCHEDULER_TASKS.value

    def __init__(
            self,
            task_id: Optional[str] = None,
            task_name: Optional[str] = None,
    ):
        detail_list = []

        if task_id is not None:
            detail_list.append(f"ID={task_id}")

        if task_name is not None:
            detail_list.append(f"Name={task_name}")

        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Task {' '.join(detail_list)} already running"
        )


class MaxPendingTasksReached(RegisteredHTTPException):
    name = 'MAX_PENDING_TASKS_REACHED'
    code = 'MAX_PENDING_TASKS'
    description = 'Достигнуто максимальное количество ожидающих задач'
    category = ExceptionCategory.SERVICE_PROJECT_SCHEDULER_TASKS.value

    def __init__(self, max_pending_tasks: int):
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Max pending tasks reached ({max_pending_tasks})"
        )


class CronForTaskNotFound(RegisteredHTTPException):
    def __init__(
            self,
            task_id: Optional[str] = None,
            task_name: Optional[str] = None,
    ):
        detail_list = []

        if task_id is not None:
            detail_list.append(f"ID={task_id}")

        if task_name is not None:
            detail_list.append(f"Name={task_name}")

        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Cron for task {' '.join(detail_list)} not found"
        )


class SQLQueryMetadataExtractionError(RegisteredHTTPException):
    name = 'SQL_QUERY_METADATA_EXTRACTION_ERROR'
    code = 'METADATA_EXTRACTION_ERROR'
    description = 'Ошибка при извлечении метаданных из SQL запроса'
    category = ExceptionCategory.DB.value

    def __init__(self, detail: str):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": self.code,
                "detail": detail,
            }
        )


class CreateTableError(RegisteredHTTPException):
    name = 'CREATE_TABLE_ERROR'
    code = 'CREATE_TABLE_ERROR'
    description = 'Ошибка при создании таблицы'
    category = ExceptionCategory.DB.value

    def __init__(self, detail: str):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": self.code,
                "detail": detail,
            }
        )


class RecreateTableError(RegisteredHTTPException):
    name = "RECREATE_TABLE_ERROR"
    code = "RECREATE_TABLE_ERROR"
    description = "Ошибка при пересоздании таблицы"
    category = ExceptionCategory.DB.value

    def __init__(self, detail: str):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": self.code,
                "detail": detail,
            },
        )


class TruncateTableError(RegisteredHTTPException):
    name = "TRUNCATE_TABLE_ERROR"
    code = "TRUNCATE_TABLE_ERROR"
    description = "Ошибка при очистке таблицы"
    category = ExceptionCategory.DB.value

    def __init__(self, detail: str):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": self.code,
                "detail": detail,
            },
        )


class ResolveWriteColumnsError(RegisteredHTTPException):
    name = 'RESOLVE_WRITE_COLUMNS_ERROR'
    code = 'RESOLVE_WRITE_COLUMNS_ERROR'
    description = 'Ошибка при согласовании колонок для записи в таблицу'
    category = ExceptionCategory.DB.value

    def __init__(self, detail: str):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": self.code,
                "detail": detail,
            }
        )


class ApplyTableColumnActionsError(RegisteredHTTPException):
    name = 'APPLY_TABLE_COLUMN_ACTIONS_ERROR'
    code = 'APPLY_TABLE_COLUMN_ACTIONS_ERROR'
    description = 'Ошибка при изменении колонок таблицы'
    category = ExceptionCategory.DB.value

    def __init__(self, detail: str):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": self.code,
                "detail": detail,
            }
        )


class DDLError(RegisteredHTTPException):
    name = 'DDL_ERROR'
    code = 'DDL_ERROR'
    description = 'Ошибка при выполнении DDL'
    category = ExceptionCategory.DB.value

    def __init__(self, detail: str):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": self.code,
                "detail": detail,
            }
        )

class StorageFTPError(RegisteredHTTPException):
    name = 'STORAGE_FTP'
    code = 'STORAGE_FTP'
    description = 'Ошибка в конфигурации для FTP'
    category = ExceptionCategory.FTP.value
