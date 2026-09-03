from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

from ..providers import AppSettingsProvider
from .set_setting_value import SetSettingValueUseCase


class EnsureSettingUseCase:
    def __init__(self, provider: AppSettingsProvider) -> None:
        self.provider = provider

    async def execute(
        self,
        key: str,
        factory: Callable[[], Any],
        *,
        changed_by: str | None = None,
        change_reason: str | None = None,
        force: bool = False,
    ) -> Any:
        settings = await self.provider.get_settings()
        current_value = settings.get(key)
        if current_value is not None and current_value != "":
            return current_value

        produced_value = factory()
        if inspect.isawaitable(produced_value):
            produced_value = await produced_value

        setter = SetSettingValueUseCase(self.provider)
        saved = await setter.execute(
            key,
            produced_value,
            changed_by=changed_by,
            change_reason=change_reason,
            force=force,
        )
        return saved.value
