from typing import Literal

from .base import EventBase
from .types import EventType


class StatusUpdateEvent(EventBase):
    type: Literal[EventType.STATUS] = EventType.STATUS
