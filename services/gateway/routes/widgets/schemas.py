from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from src.enums import WorkerStatus
from src.modules.task_execution.domain.types import TaskExecutionStatus
from src.schemas.http.system import SystemStateValue

# --- Запуски за 24 ч ---


class RunsBucketSchema(BaseModel):
    start: datetime = Field(
        description="Начало корзины (UTC). Корзина длится bucket_minutes, "
                    "последняя заканчивается в window_end",
    )
    total: int = Field(ge=0)
    success: int = Field(ge=0)
    error: int = Field(ge=0)
    cancelled: int = Field(ge=0)
    running: int = Field(ge=0, description="Запуски, ещё не завершившиеся")


class RunsLast24hWidgetSchema(BaseModel):
    generated_at: datetime
    window_start: datetime
    window_end: datetime
    bucket_minutes: int = Field(ge=1)
    total: int = Field(ge=0)
    success: int = Field(ge=0)
    error: int = Field(ge=0)
    cancelled: int = Field(ge=0)
    running: int = Field(ge=0)
    success_ratio: float | None = Field(
        ge=0,
        le=1,
        description="success / (success + error); null, если завершённых запусков нет. "
                    "Отменённые и незавершённые в долю не входят",
    )
    buckets: list[RunsBucketSchema] = Field(
        description="Почасовые корзины от старых к новым, всегда 24 элемента",
    )


# --- Ближайшие запуски по расписанию ---


class ScheduledRunItemSchema(BaseModel):
    project_id: str
    project_name: str | None
    cron: str
    next_run_time: datetime
    last_run_status: TaskExecutionStatus | None
    last_run_time: datetime | None


class ScheduledRunsWidgetSchema(BaseModel):
    generated_at: datetime
    total_schedules: int = Field(ge=0, description="Доступных расписаний, включая отключённые")
    disabled_schedules: int = Field(ge=0)
    items: list[ScheduledRunItemSchema] = Field(
        description="Ближайшие запуски, отсортированы по next_run_time",
    )


# --- Сервисы ---


class ServiceStatusItemSchema(BaseModel):
    name: Literal["gateway", "project_scheduler", "orchestrator"]
    status: WorkerStatus
    latency_ms: float | None = Field(
        description="Время ответа сервиса из gateway; null для самого gateway и при недоступности",
    )
    uptime_seconds: float | None


class WorkersSummarySchema(BaseModel):
    total: int = Field(ge=0)
    online: int = Field(ge=0)
    busy: int = Field(ge=0, description="Воркеры, выполняющие задачу")


class ServicesWidgetSchema(BaseModel):
    generated_at: datetime
    system_state: SystemStateValue
    services: list[ServiceStatusItemSchema]
    workers: WorkersSummarySchema


# --- Проблемные проекты ---


class FailingProjectItemSchema(BaseModel):
    project_id: str
    project_name: str | None
    error_count: int = Field(ge=0)
    total_count: int = Field(ge=0, description="Завершённых запусков за окно")
    last_error_at: datetime
    consecutive_failures: int = Field(
        ge=0,
        description="Сколько последних завершённых запусков подряд упали "
                    "(отменённые и незавершённые пропускаются)",
    )


class FailingProjectsWidgetSchema(BaseModel):
    generated_at: datetime
    window_start: datetime
    window_end: datetime
    items: list[FailingProjectItemSchema] = Field(
        description="Проекты по убыванию числа ошибок",
    )
