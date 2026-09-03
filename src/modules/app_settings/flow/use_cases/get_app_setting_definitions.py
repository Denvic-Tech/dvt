from __future__ import annotations

from ...domain.definitions import SettingDefinition
from ...domain.registry import SettingsRegistry


class GetAppSettingDefinitionsUseCase:
    def __init__(self, registry: type[SettingsRegistry]) -> None:
        self.registry = registry

    def execute(self) -> list[SettingDefinition]:
        return self.registry.all_definitions()
