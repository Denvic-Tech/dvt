from __future__ import annotations

from typing import Protocol

from ..value_objects import AppSettingsValue


class AppSettingsCache[SettingsT: AppSettingsValue](Protocol):
    async def get(self) -> SettingsT | None: ...

    async def set(self, settings: SettingsT) -> None: ...

    async def invalidate(self) -> None: ...
