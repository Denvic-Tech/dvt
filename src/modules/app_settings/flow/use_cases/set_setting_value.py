from __future__ import annotations

from datetime import UTC, datetime

from ...domain.entities import SettingValue
from ...domain.events import AppSettingCreated, AppSettingUpdated
from ...domain.exceptions import SettingReadOnlyError
from ...domain.gateways import AppSettingEventPublisher
from ..providers import AppSettingsProvider


class SetSettingValueUseCase:
    def __init__(
        self,
        provider: AppSettingsProvider,
        *,
        event_publisher: AppSettingEventPublisher | None = None,
    ) -> None:
        self.provider = provider
        self.event_publisher = event_publisher

    async def execute(
        self,
        key: str,
        value: object,
        *,
        changed_by: str | None = None,
        change_reason: str | None = None,
        force: bool = False,
    ) -> SettingValue:
        definition = self.provider.registry.get_definition(key)
        if not force and not definition.runtime_editable:
            raise SettingReadOnlyError(f"App setting is not editable at runtime: {key}")

        existing = await self.provider.repository.get_values([key])
        validated = self.provider.registry.validate_value(key, value)
        saved = await self.provider.repository.save(
            SettingValue(key=key, value=validated),
            changed_by=changed_by,
            change_reason=change_reason,
        )
        await self.provider.invalidate_cache()

        if self.event_publisher is not None:
            event_cls = AppSettingUpdated if key in existing else AppSettingCreated
            await self.event_publisher.publish(
                event_cls(
                    key=key,
                    version=saved.version,
                    changed_at=saved.updated_at or datetime.now(UTC),
                )
            )

        return saved
