import time

from pydantic import BaseModel, Field

from .types import EventType


class EventBase(BaseModel):
    """Базовая модель для всех событий."""
    type: EventType = Field(..., description="Тип сообщения")
    timestamp: int = Field(default_factory=lambda: int(time.time() * 1000))
