from src.modules.extension_management.domain.entities import Extension
from src.modules.extension_management.domain.gateways.extension_management import (
    ExtensionPackageGateway,
)


class InstallExtensionPackageUseCase:
    def __init__(self, gateway: ExtensionPackageGateway) -> None:
        self._gateway = gateway

    async def execute(
        self,
        package_id: str,
        *,
        allow_downgrade: bool = False,
        allow_reinstall: bool = False,
    ) -> Extension:
        return await self._gateway.install_uploaded_package(
            package_id,
            allow_downgrade=allow_downgrade,
            allow_reinstall=allow_reinstall,
        )
