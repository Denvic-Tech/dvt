from typing import Protocol, Optional, TYPE_CHECKING

from src.enums import BaseEnum

if TYPE_CHECKING:
    from .event import Event


class EventType(str, BaseEnum):
    """Типы событий от сервера к клиенту."""
    PING = "PING"
    STATUS = "STATUS"  # Обновление статуса очереди (и начальный статус)
    NODE_METADATA = "NODE_METADATA"  # Метаданные узла (типы входов/выходов и т.д.)
    NODE_EXECUTION_STATUS = "NODE_EXECUTION_STATUS"  # Статус выполнения узла
    TASK_EXECUTION_STATUS = "TASK_EXECUTION_STATUS"  # Статус выполнения задачи
    TASK_EXECUTION_TELEMETRY = "TASK_EXECUTION_TELEMETRY"
    PROGRESS = "PROGRESS"  # Прогресс выполнения узла
    LOG_EVENT = "LOG_EVENT"


class EventCallback(Protocol):
    def __call__(
            self,
            event: "Event",
            user_id: Optional[str] = None,
            project_id: Optional[str] = None,
    ):
        ...
