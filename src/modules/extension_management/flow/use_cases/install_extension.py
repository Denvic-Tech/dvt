from src.modules.extension_management.domain.entities import Extension
from src.modules.extension_management.domain.gateways.extension_management import (
    ExtensionLifecycleGateway,
)


class InstallExtensionUseCase:
    def __init__(self, gateway: ExtensionLifecycleGateway) -> None:
        self._gateway = gateway

    async def execute(
        self,
        name: str,
        version: str | None = None,
        *,
        allow_downgrade: bool = False,
        allow_reinstall: bool = False,
    ) -> Extension:
        return await self._gateway.install_extension(
            name, version=version,
            allow_downgrade=allow_downgrade, allow_reinstall=allow_reinstall,
        )
