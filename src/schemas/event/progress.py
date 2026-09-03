from typing import Literal, Optional

from pydantic import Field

from .base import EventBase
from .types import EventType


class ProgressEvent(EventBase):
    type: Literal[EventType.PROGRESS] = EventType.PROGRESS

    value: int = Field(description="Текущее значение прогресса")
    max: int = Field(description="Максимальное значение прогресса")
    task_id: str = Field(description="ID текущей задачи")
    node_id: Optional[str] = Field(None, description="ID узла, для которого отображается прогресс")
