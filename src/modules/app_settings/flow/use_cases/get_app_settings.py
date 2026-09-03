from __future__ import annotations

from ...domain.value_objects import AppSettingsValue
from ..providers import AppSettingsProvider


class GetAppSettingsUseCase[SettingsT: AppSettingsValue]:
    def __init__(self, provider: AppSettingsProvider[SettingsT]) -> None:
        self.provider = provider

    async def execute(self) -> SettingsT:
        return await self.provider.get_settings()
