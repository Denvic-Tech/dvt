from typing import Literal

from .base import EventBase
from .types import EventType


class PingEvent(EventBase):
    type: Literal[EventType.PING] = EventType.PING
