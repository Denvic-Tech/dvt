from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from ..entities import SettingChange, SettingValue


class AppSettingsRepository(Protocol):
    async def get_values(self, keys: Iterable[str]) -> dict[str, SettingValue]: ...

    async def save(
        self,
        value: SettingValue,
        *,
        changed_by: str | None = None,
        change_reason: str | None = None,
    ) -> SettingValue: ...

    async def delete(
        self,
        key: str,
        *,
        changed_by: str | None = None,
        change_reason: str | None = None,
    ) -> SettingChange | None: ...

    async def get_history(self, key: str) -> list[SettingChange]: ...
