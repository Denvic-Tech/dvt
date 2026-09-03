from __future__ import annotations

from typing import Protocol

from ..events import AppSettingEvent


class AppSettingEventPublisher(Protocol):
    async def publish(self, event: AppSettingEvent) -> None: ...
