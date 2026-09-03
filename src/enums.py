from enum import Enum
from functools import lru_cache
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.pipeline.execution_mode import PipelineExecutionMode as ExecMode  # noqa: F403


class BaseEnum(Enum):
    """Базовый enum, у которого есть .values() и .names()."""

    @classmethod
    @lru_cache
    def values(cls) -> list[str]:
        return [member.value for member in cls]

    @classmethod
    @lru_cache
    def names(cls) -> list[str]:
        return [member.name for member in cls]

    def __str__(self):
        return self.value


class DVTDefaultRoles(BaseEnum):
    SUPERADMIN = "superadmin"
    ADMIN = "admin"
    USER = "user"


class Locales(BaseEnum):
    EN = "en"
    RU = "ru"
    DE = "de"


class NodeType(BaseEnum):
    BASE = "BASE"
    DATAFRAME_OUTPUT = "DATAFRAME_OUTPUT"
    CONNECTION_OUTPUT = "CONNECTION_OUTPUT"
    PRIMITIVE = "PRIMITIVE"
    INTERNAL = "INTERNAL"
    TESTING = "TESTING"
    WIDGET = "WIDGET"


class ExecutionStatus(str, BaseEnum):
    """Статусы выполнения узла."""
    IDLE = "idle"
    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"
    CANCELLED = "cancelled"


class RetryBackoff(str, BaseEnum):
    FIXED = "fixed"
    EXPONENTIAL = "exponential"


class WorkerStatus(str, BaseEnum):
    ONLINE = "online"
    OFFLINE = "offline"


class AIAnalysisStatus(str, BaseEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"


class OOMGuardMode(str, BaseEnum):
    DISABLED = "DISABLED"
    HOST_PRESSURE = "HOST_PRESSURE"
    WORKER_THRESHOLD = "WORKER_THRESHOLD"


class OOMWorkerThresholdType(str, BaseEnum):
    PERCENT = "PERCENT"
    ABSOLUTE_MB = "ABSOLUTE_MB"


class ExtensionDepsStatus(str, BaseEnum):
    """Статус установки зависимостей расширения."""
    NOT_INSTALLED = "not_installed"
    INSTALLING = "installing"
    READY = "ready"
    ERROR = "error"


def __getattr__(name: str) -> Any:
    if name == "ExecMode":
        # TODO: remove this import from B24 extension!!!
        from src.pipeline.execution_mode import PipelineExecutionMode

        # Кэшируем alias после первого обращения.
        globals()[name] = PipelineExecutionMode
        return PipelineExecutionMode

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")