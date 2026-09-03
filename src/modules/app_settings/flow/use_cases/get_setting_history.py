from __future__ import annotations

from ...domain.entities import SettingChange
from ..providers import AppSettingsProvider


class GetSettingHistoryUseCase:
    def __init__(self, provider: AppSettingsProvider) -> None:
        self.provider = provider

    async def execute(self, key: str) -> list[SettingChange]:
        self.provider.registry.get_definition(key)
        return await self.provider.repository.get_history(key)
