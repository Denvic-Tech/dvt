import time
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from .task_payload import TaskInternal


class OrchestratorCommandType(StrEnum):
    """Transport discriminator; intentionally not a task domain enum."""

    NESTED_TASK_ENQUEUE = "NESTED_TASK_ENQUEUE"


class OrchestratorCommandBase(BaseModel):
    type: OrchestratorCommandType = Field(..., description="Тип команды оркестратору")
    timestamp: int = Field(default_factory=lambda: int(time.time() * 1000))


class NestedTaskEnqueueCommand(OrchestratorCommandBase):
    type: Literal[OrchestratorCommandType.NESTED_TASK_ENQUEUE] = (
        OrchestratorCommandType.NESTED_TASK_ENQUEUE
    )
    request_id: str = Field(..., description="Уникальный идентификатор команды")
    task: TaskInternal = Field(..., description="Подготовленная дочерняя задача")
    origin_worker_id: str = Field(..., description="Идентификатор воркера-инициатора")
    parent_task_id: str = Field(..., description="Идентификатор родительской задачи")
    parent_project_id: str = Field(..., description="Идентификатор родительского проекта")
    wait_for_completion: bool = Field(
        default=False,
        description="Требуется ли синхронное ожидание дочерней задачи",
    )


OrchestratorCommand = Annotated[
    NestedTaskEnqueueCommand,
    Field(discriminator="type"),
]
