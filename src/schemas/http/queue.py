from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from src.modules.task_execution.domain.types import TaskExecutionStatus, TaskSource
from src.pipeline.execution_mode import PipelineExecutionMode
from src.schemas.http.common import CommonResponse


class QueueTask(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    task_id: str = Field(..., description="Task identifier")
    project_id: str = Field(..., description="Related project identifier")
    mode: PipelineExecutionMode = Field(..., description="Execution mode")
    force_exec: bool = Field(default=False, description="Whether the task was forced to execute")
    queued_at: datetime = Field(..., description="Timestamp when task was enqueued")
    status: TaskExecutionStatus = Field(..., description="Current status of the task")
    termination_reason: str | None = Field(default=None, description="Reason for task termination if applicable")
    assigned_worker_id: str | None = Field(default=None, description="Identifier of the worker assigned to the task")
    source: TaskSource = Field(..., description="Task source")
    started_at: datetime | None = Field(default=None, description="Timestamp when task was started")
    finished_at: datetime | None = Field(default=None, description="Timestamp when task was finished")
    message: str | None = Field(default=None, description="Task message")


class QueueStateResponse(BaseModel):
    tasks: list[QueueTask] = Field(default_factory=list, description="List of pending tasks")


class QueueAction(StrEnum):
    CANCEL = "cancel"


class QueueActionRequest(BaseModel):
    action: QueueAction = Field(..., description="Queue action to perform")
    task_id: str = Field(..., description="Task identifier to apply the action to")


class QueueActionResponse(CommonResponse):
    task_id: str = Field(..., description="Task identifier the action was applied to")
