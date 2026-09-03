from typing import Literal, Optional

from pydantic import Field

from src.enums import ExecutionStatus
from src.pipeline.execution_mode import PipelineExecutionMode

from .base import EventBase
from .types import EventType


class NodeExecutionStatusEvent(EventBase):
    type: Literal[EventType.NODE_EXECUTION_STATUS] = EventType.NODE_EXECUTION_STATUS

    task_id: str = Field(description="ID текущей задачи")
    node_id: str = Field(description="ID выполняемого узла (для отображения)")
    status: ExecutionStatus = Field(description="Текущий статус выполнения узла")
    execution_mode: PipelineExecutionMode = Field(description="Режим выполнения задачи")
    message: str | None = Field(
        default=None,
        description="Сообщение об ошибке узла",
    )
