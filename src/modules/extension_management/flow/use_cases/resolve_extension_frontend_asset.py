from pathlib import Path

from src.modules.extension_management.domain.gateways.extension_management import (
    ExtensionQueryGateway,
)


class ResolveExtensionFrontendAssetUseCase:
    def __init__(self, gateway: ExtensionQueryGateway) -> None:
        self._gateway = gateway

    async def execute(self, name: str, asset_path: str) -> Path:
        return await self._gateway.resolve_frontend_asset(name, asset_path)
