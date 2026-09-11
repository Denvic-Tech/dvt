from src.modules.extension_management.domain.entities import Extension
from src.modules.extension_management.domain.gateways.extension_management import (
    ExtensionLifecycleGateway,
)


class SyncInstalledExtensionsUseCase:
    def __init__(self, gateway: ExtensionLifecycleGateway) -> None:
        self._gateway = gateway

    async def execute(self) -> list[Extension]:
        return await self._gateway.sync_installed_extensions()
