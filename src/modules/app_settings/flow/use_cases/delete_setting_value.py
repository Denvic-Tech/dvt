from __future__ import annotations

from ...domain.events import AppSettingDeleted
from ...domain.gateways import AppSettingEventPublisher
from ..providers import AppSettingsProvider


class DeleteSettingValueUseCase:
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
        *,
        changed_by: str | None = None,
        change_reason: str | None = None,
    ) -> bool:
        self.provider.registry.get_definition(key)
        change = await self.provider.repository.delete(
            key,
            changed_by=changed_by,
            change_reason=change_reason,
        )
        await self.provider.invalidate_cache()
        if change is None:
            return False

        if self.event_publisher is not None:
            await self.event_publisher.publish(
                AppSettingDeleted(key=key, version=0, changed_at=change.changed_at)
            )
        return True
