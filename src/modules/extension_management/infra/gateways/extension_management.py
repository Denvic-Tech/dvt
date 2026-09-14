from __future__ import annotations

from pathlib import Path
from typing import BinaryIO

from src.modules.extension_management.domain.entities import Extension
from src.modules.extension_management.domain.value_objects import (
    ExtensionFrontendBundle,
    ExtensionPackagePreview,
)
from src.modules.extension_management.infra.management_service import ExtensionManager
from src.modules.extension_management.infra.mappers import (
    extension_record_to_domain,
    package_preview_to_domain,
)


class ExtensionManagementGatewayAdapter:
    """Map the legacy technical coordinator onto domain/application contracts."""

    def __init__(self, manager: ExtensionManager) -> None:
        self._manager = manager

    async def list_extensions(self) -> list[Extension]:
        return [extension_record_to_domain(item) for item in await self._manager.list_extensions()]

    async def get_extension(self, name: str) -> Extension | None:
        item = await self._manager.get_extension(name)
        return extension_record_to_domain(item) if item is not None else None

    async def get_frontend_bundle_info(self, name: str) -> ExtensionFrontendBundle:
        info = await self._manager.get_frontend_bundle_info(name)
        return ExtensionFrontendBundle(
            bundle_path=info.bundle_path,
            assets_root=info.assets_root,
            entry_file=info.entry_file,
            entrypoint=info.entrypoint,
        )

    async def resolve_frontend_asset(self, name: str, asset_path: str) -> Path:
        return await self._manager.resolve_frontend_asset(name, asset_path)

    async def sync_available_extensions(self) -> list[Extension]:
        return [
            extension_record_to_domain(item)
            for item in await self._manager.sync_available_extensions()
        ]

    async def sync_installed_extensions(self) -> list[Extension]:
        return [
            extension_record_to_domain(item)
            for item in await self._manager.sync_installed_extensions()
        ]

    async def install_extension(self, name: str, version: str | None = None) -> Extension:
        return extension_record_to_domain(
            await self._manager.install_extension(name, version=version)
        )

    async def uninstall_extension(
        self, name: str, *, drop_extension_data: bool = False
    ) -> Extension:
        return extension_record_to_domain(
            await self._manager.uninstall_extension(
                name, drop_extension_data=drop_extension_data
            )
        )

    async def reload_extension(self, name: str) -> Extension:
        return extension_record_to_domain(await self._manager.reload_extension(name))

    async def set_enabled(self, name: str, enabled: bool) -> Extension:
        return extension_record_to_domain(await self._manager.set_enabled(name, enabled))

    async def preview_uploaded_package(
        self, fileobj: BinaryIO, filename: str | None
    ) -> ExtensionPackagePreview:
        return package_preview_to_domain(
            await self._manager.preview_uploaded_package(fileobj, filename)
        )

    async def install_uploaded_package(
        self,
        package_id: str,
        *,
        allow_downgrade: bool = False,
        allow_reinstall: bool = False,
    ) -> Extension:
        return extension_record_to_domain(
            await self._manager.install_uploaded_package(
                package_id,
                allow_downgrade=allow_downgrade,
                allow_reinstall=allow_reinstall,
            )
        )


__all__ = ["ExtensionManagementGatewayAdapter"]
