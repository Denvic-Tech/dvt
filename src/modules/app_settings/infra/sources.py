from __future__ import annotations

import os
from collections.abc import Iterable
from typing import Any

from src.modules.app_settings.domain.definitions import SettingDefinition
from src.modules.app_settings.domain.gateways import AppSettingsValueSource


class EnvironmentSettingsSource(AppSettingsValueSource):
    async def get_values(self, definitions: Iterable[SettingDefinition]) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for definition in definitions:
            if not definition.read_env:
                continue
            env_var = definition.env_var
            if not env_var:
                continue
            env_value = os.getenv(env_var)
            if env_value is not None:
                values[definition.key] = env_value
        return values


class EmptySecretSettingsSource(AppSettingsValueSource):
    async def get_values(self, definitions: Iterable[SettingDefinition]) -> dict[str, Any]:
        return {}
