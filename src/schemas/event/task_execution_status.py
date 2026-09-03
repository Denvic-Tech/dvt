from typing import Literal

from pydantic import BaseModel, Field

from src.modules.task_execution.domain.types import TaskExecutionStatus
from src.pipeline.execution_mode import PipelineExecutionMode

from .base import EventBase
from .types import EventType


class TaskError(BaseModel):
    message: str = Field(description="Сообщение об ошибке")


class TaskExecutionStatusEvent(EventBase):
    type: Literal[EventType.TASK_EXECUTION_STATUS] = EventType.TASK_EXECUTION_STATUS

    task_id: str = Field(description="ID текущей задачи")
    mode: PipelineExecutionMode = Field(
        description="Режим выполнения задачи"
    )
    status: TaskExecutionStatus = Field(
        description="Текущий статус выполнения задачи",
    )

    error: TaskError | None = Field(default=None)
