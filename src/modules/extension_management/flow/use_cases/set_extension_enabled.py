from src.modules.extension_management.domain.entities import Extension
from src.modules.extension_management.domain.gateways.extension_management import (
    ExtensionLifecycleGateway,
)


class SetExtensionEnabledUseCase:
    def __init__(self, gateway: ExtensionLifecycleGateway) -> None:
        self._gateway = gateway

    async def execute(self, name: str, *, enabled: bool) -> Extension:
        return await self._gateway.set_enabled(name, enabled)
