from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.enums import RetryBackoff
from src.modules.project.domain import ProjectScheduleRunStatus
from src.modules.task_execution.domain.types import TaskExecutionStatus
from src.pipeline.execution_mode import PipelineExecutionMode


def validate_retry_policy(
    *,
    retry_backoff: RetryBackoff,
    retry_delay_seconds: int,
    retry_max_delay_seconds: int,
) -> None:
    if retry_backoff == RetryBackoff.EXPONENTIAL and retry_max_delay_seconds < retry_delay_seconds:
        raise ValueError(
            "retry_max_delay_seconds must be greater than or equal to "
            "retry_delay_seconds for exponential backoff"
        )


class ProjectScheduleRequest(BaseModel):
    project_id: str = Field(..., description="ID проекта")
    mode: PipelineExecutionMode = Field(PipelineExecutionMode.FULL, description="Режим выполнения задачи")
    force_exec: bool = Field(False, description="Принудительное выполнение")
    cron: str = Field(..., description="Выражение CRON для планирования проекта")
    max_retries: int = Field(0, ge=0, le=10, description="Количество повторов после ошибки")
    retry_delay_seconds: int = Field(
        60,
        ge=1,
        le=86400,
        description="Базовая задержка между попытками в секундах",
    )
    retry_backoff: RetryBackoff = Field(
        RetryBackoff.FIXED,
        description="Стратегия увеличения задержки между попытками",
    )
    retry_max_delay_seconds: int = Field(
        3600,
        ge=1,
        le=86400,
        description="Максимальная задержка exponential backoff",
    )

    @model_validator(mode="after")
    def validate_retry_settings(self):
        validate_retry_policy(
            retry_backoff=self.retry_backoff,
            retry_delay_seconds=self.retry_delay_seconds,
            retry_max_delay_seconds=self.retry_max_delay_seconds,
        )
        return self


class ProjectScheduleServiceRequest(ProjectScheduleRequest):
    scheduled_by_user_id: str = Field(..., description="ID пользователя, сохранившего расписание")


class ProjectSchedulePatchRequest(BaseModel):
    cron: str | None = Field(None, description="Новое выражение CRON для расписания проекта")
    scheduled_by_user_id: str | None = Field(
        None,
        description="ID пользователя, который последним сохранил расписание",
    )
    mode: PipelineExecutionMode | None = Field(None, description="Новый режим выполнения задачи")
    force_exec: bool | None = Field(
        None, description="Новое значение принудительного выполнения"
    )
    disabled: bool | None = Field(None, description="Новое состояние расписания")
    max_retries: int | None = Field(None, ge=0, le=10, description="Новое количество повторов")
    retry_delay_seconds: int | None = Field(
        None,
        ge=1,
        le=86400,
        description="Новая базовая задержка между попытками",
    )
    retry_backoff: RetryBackoff | None = Field(None, description="Новая retry-стратегия")
    retry_max_delay_seconds: int | None = Field(
        None,
        ge=1,
        le=86400,
        description="Новая максимальная задержка exponential backoff",
    )


class ProjectScheduleRunChainResponse(BaseModel):
    run_id: str = Field(..., description="ID цепочки запуска")
    state: ProjectScheduleRunStatus = Field(..., description="Состояние цепочки запуска")
    attempt_number: int = Field(..., ge=0, description="Номер текущей или последней попытки")
    max_attempts: int = Field(..., ge=1, description="Первичный запуск плюс допустимые повторы")
    current_task_id: str | None = Field(None, description="ID текущей или последней Task")
    next_retry_at: datetime | None = Field(None, description="Время следующего повтора")
    last_error: str | None = Field(None, description="Последняя ошибка цепочки")
    started_at: datetime = Field(..., description="Время создания цепочки")
    finished_at: datetime | None = Field(None, description="Время завершения цепочки")


class ProjectScheduleRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    task_id: str = Field(..., description="ID запуска проекта")
    status: TaskExecutionStatus = Field(..., description="Статус запуска проекта")
    queued_at: datetime = Field(..., description="Время постановки запуска в очередь")
    started_at: datetime | None = Field(None, description="Время начала запуска проекта")
    finished_at: datetime | None = Field(None, description="Время завершения запуска проекта")
    message: str | None = Field(None, description="Краткое сообщение о результате запуска")
    termination_reason: str | None = Field(
        None, description="Причина аварийного завершения запуска"
    )
    schedule_run_id: str | None = Field(None, description="ID цепочки scheduler-запуска")
    attempt_number: int | None = Field(None, description="Номер попытки в цепочке")
    is_retry: bool = Field(False, description="Является ли запуск повторной попыткой")


class ProjectScheduleResponse(ProjectScheduleRequest):
    """Схема данных для возврата данных о расписаниях проектов."""

    disabled: bool = Field(False, description="Отключено ли расписание")
    scheduled_by_user_id: str | None = Field(
        None,
        description="ID пользователя, который последним сохранил расписание",
    )
    task_id: str | None = Field(None, description="ID задачи в планировщике")
    next_run_time: datetime | None = Field(None, description="Время следующего запуска")
    last_run_time: datetime | None = Field(None, description="Время последнего запуска проекта")
    last_run_status: TaskExecutionStatus | None = Field(
        None, description="Статус последнего запуска проекта"
    )
    last_run_task_id: str | None = Field(None, description="ID последнего запуска проекта")
    last_run_message: str | None = Field(
        None, description="Сообщение последнего запуска проекта"
    )
    last_run_termination_reason: str | None = Field(
        None,
        description="Причина аварийного завершения последнего запуска проекта",
    )
    recent_runs: list[ProjectScheduleRunResponse] = Field(
        default_factory=list,
        description="История последних scheduler-запусков проекта",
    )
    latest_run_chain: ProjectScheduleRunChainResponse | None = Field(
        None,
        description="Состояние последней цепочки запуска расписания",
    )
