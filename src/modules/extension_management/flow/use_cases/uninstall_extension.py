from src.modules.extension_management.domain.entities import Extension
from src.modules.extension_management.domain.gateways.extension_management import (
    ExtensionLifecycleGateway,
)


class UninstallExtensionUseCase:
    def __init__(self, gateway: ExtensionLifecycleGateway) -> None:
        self._gateway = gateway

    async def execute(
        self, name: str, *, drop_extension_data: bool = False
    ) -> Extension:
        return await self._gateway.uninstall_extension(
            name, drop_extension_data=drop_extension_data
        )
