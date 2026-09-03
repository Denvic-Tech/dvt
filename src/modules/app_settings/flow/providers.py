from __future__ import annotations

from src.modules.app_settings.domain.gateways import AppSettingsCache, AppSettingsValueSource
from src.modules.app_settings.domain.registry import SettingsRegistry
from src.modules.app_settings.domain.repositories import AppSettingsRepository
from src.modules.app_settings.domain.value_objects import AppSettingsValue


class AppSettingsProvider[SettingsT: AppSettingsValue]:
    def __init__(
        self,
        *,
        registry: type[SettingsRegistry[SettingsT]],
        repository: AppSettingsRepository,
        cache: AppSettingsCache[SettingsT] | None = None,
        env_source: AppSettingsValueSource | None = None,
        secret_source: AppSettingsValueSource | None = None,
    ) -> None:
        self.registry = registry
        self.repository = repository
        self.cache = cache
        self.env_source = env_source
        self.secret_source = secret_source

    async def get_settings(self) -> SettingsT:
        if self.cache is not None:
            cached = await self.cache.get()
            if cached is not None:
                return cached

        definitions = self.registry.all_definitions()
        values = self.registry.default_values()

        if self.secret_source is not None:
            values.update(await self.secret_source.get_values(definitions))
        if self.env_source is not None:
            values.update(await self.env_source.get_values(definitions))

        persisted = await self.repository.get_values(definition.key for definition in definitions)
        values.update({key: item.value for key, item in persisted.items()})

        settings = self.registry.build_runtime_model(self.registry.validate_values(values))
        if self.cache is not None:
            await self.cache.set(settings)
        return settings

    async def invalidate_cache(self) -> None:
        if self.cache is not None:
            await self.cache.invalidate()
