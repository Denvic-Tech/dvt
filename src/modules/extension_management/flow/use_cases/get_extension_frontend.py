from src.modules.extension_management.domain.gateways.extension_management import (
    ExtensionQueryGateway,
)
from src.modules.extension_management.domain.value_objects import ExtensionFrontendBundle


class GetExtensionFrontendUseCase:
    def __init__(self, gateway: ExtensionQueryGateway) -> None:
        self._gateway = gateway

    async def execute(self, name: str) -> ExtensionFrontendBundle:
        return await self._gateway.get_frontend_bundle_info(name)
