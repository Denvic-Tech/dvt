from src.modules.extension_management.domain.entities import Extension
from src.modules.extension_management.domain.gateways.extension_management import (
    ExtensionLifecycleGateway,
)


class ReloadExtensionUseCase:
    def __init__(self, gateway: ExtensionLifecycleGateway) -> None:
        self._gateway = gateway

    async def execute(self, name: str) -> Extension:
        return await self._gateway.reload_extension(name)
