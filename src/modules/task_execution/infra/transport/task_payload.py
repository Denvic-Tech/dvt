from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from src.modules.task_execution.domain.types import TaskSource
from src.pipeline.execution_mode import PipelineExecutionMode
from src.pipeline.types import Pipeline
from src.schemas.internal.project_settings import ProjectSettings
from src.schemas.internal.project_variables import ProjectVariables


class TaskInternalBase(BaseModel):
    """Internal pipeline-execution transport payload shared by service boundaries."""

    project_id: str = Field(..., description="ID проекта")
    task_id: str | None = Field(None, description="ID задачи")
    queued_at: datetime = Field(
        default_factory=lambda: datetime.now(tz=UTC),
        description="Момент постановки execution в очередь; участвует в строгом порядке запусков",
    )
    pipeline: Pipeline = Field(description="Структура пайплайна для выполнения")
    mode: PipelineExecutionMode = Field(
        PipelineExecutionMode.FULL,
        description="Режим выполнения pipeline",
    )
    send_ws_messages: bool = Field(True, description="Отправлять сообщения в WS")
    source: TaskSource = Field(TaskSource.API, description="Источник задачи")
    retry_count: int = Field(default=0, description="Количество предыдущих попыток")
    force_exec: bool = Field(default=False, description="Принудительное выполнение")
    project_settings: ProjectSettings = Field(description="Настройки проекта")
    project_variables: ProjectVariables = Field(description="Переменные проекта")
    extension_names: list[str] = Field(
        default_factory=list,
        description="Расширения, задействованные в pipeline",
    )

    @field_validator("pipeline")
    @classmethod
    def validate_pipeline(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value:
            raise ValueError("Pipeline must not be empty")
        return value


class TaskInternal(TaskInternalBase):
    """Transport/runtime payload delivered to the execution worker."""

    user_id: str = Field(..., description="ID клиента")
    organization_id: str | None = Field(default=None, description="ID организации")
    task_id: str = Field(..., description="ID задачи")
    target_nodes: list[str] | None = Field(None, description="Узлы, которые нужно выполнить")
    metadata_changed_node_ids: list[str] | None = Field(
        None,
        description="Ноды, измененные в UI и требующие metadata-пересчета",
    )
    changed_node_ids: list[str] | None = Field(
        None,
        description="Снимок измененных нод проекта для инкрементального выполнения",
    )
    graph_revision: int | None = Field(
        None,
        description="Снимок ревизии вычислительной части графа",
    )
    schedule_run_id: str | None = Field(None, description="ID scheduler run chain")
    schedule_attempt: int | None = Field(None, ge=1, description="Номер попытки")


class TaskScheduledInternal(TaskInternal):
    """Legacy scheduler transport extension kept while scheduler payloads migrate."""

    cron: str = Field(..., description="Выражение CRON для планирования задачи")
    next_run_time: datetime | None = Field(None, description="Время следующего запуска")
