from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Protocol

from ..definitions import SettingDefinition


class AppSettingsValueSource(Protocol):
    async def get_values(self, definitions: Iterable[SettingDefinition]) -> dict[str, Any]: ...
