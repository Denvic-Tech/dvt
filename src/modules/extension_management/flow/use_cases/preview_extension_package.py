from typing import BinaryIO

from src.modules.extension_management.domain.gateways.extension_management import (
    ExtensionPackageGateway,
)
from src.modules.extension_management.domain.value_objects import ExtensionPackagePreview


class PreviewExtensionPackageUseCase:
    def __init__(self, gateway: ExtensionPackageGateway) -> None:
        self._gateway = gateway

    async def execute(
        self, fileobj: BinaryIO, filename: str | None
    ) -> ExtensionPackagePreview:
        return await self._gateway.preview_uploaded_package(fileobj, filename)
