from datetime import datetime

from pydantic import BaseModel, Field

from src.schemas.http.common import CommonResponse
from src.schemas.http.project_variable import ProjectVariableBase

from ...domain.types import TaskExecutionStatus, TaskSource


class TaskCreateRequest(BaseModel):
    variables: dict[str, ProjectVariableBase] | None = Field(
        default=None,
        description="Typed runtime-переменные для конкретного запуска",
    )


class TaskResponse(CommonResponse):
    task_id: str


class TaskInfo(BaseModel):
    task_id: str = Field(..., description="Task's ID")
    status: TaskExecutionStatus = Field(..., description="Task's status")
    started_at: datetime | None = Field(None, description="Task processing started time")
    message: str | None = Field(None, description="Optional task's message")
    source: TaskSource = Field(..., description="Task source")
