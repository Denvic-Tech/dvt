from typing import Literal

from pydantic import Field

from src.schemas.http.log import LogEntrySchema
from .base import EventBase
from .types import EventType


class LogEvent(EventBase):
    type: Literal[EventType.LOG_EVENT] = EventType.LOG_EVENT

    entry: LogEntrySchema = Field(description="Запись лога")
