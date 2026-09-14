from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import BinaryIO

from src.modules.extension_management.domain.entities import Extension
from src.modules.extension_management.domain.gateways.extension_management import (
    ExtensionLifecycleGateway,
    ExtensionPackageGateway,
    ExtensionQueryGateway,
)
from src.modules.extension_management.domain.repositories.extension_management import (
    ExtensionRepository,
)
from src.modules.extension_management.domain.value_objects import (
    ExtensionFrontendBundle,
    ExtensionPackagePreview,
)
from src.modules.extension_management.flow.use_cases import (
    GetExtensionFrontendUseCase,
    InstallExtensionPackageUseCase,
    InstallExtensionUseCase,
    ListExtensionsUseCase,
    PreviewExtensionPackageUseCase,
    ReloadExtensionUseCase,
    ResolveExtensionFrontendAssetUseCase,
    SetExtensionEnabledUseCase,
    SyncAvailableExtensionsUseCase,
    SyncInstalledExtensionsUseCase,
    UninstallExtensionUseCase,
)


class ExtensionManagementProvider:
    """Application facade used by service adapters and public HTTP routes."""

    def __init__(
        self,
        *,
        repository: ExtensionRepository,
        query_gateway: ExtensionQueryGateway,
        lifecycle_gateway: ExtensionLifecycleGateway,
        package_gateway: ExtensionPackageGateway,
        close_callback: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._list = ListExtensionsUseCase(repository)
        self._get_frontend = GetExtensionFrontendUseCase(query_gateway)
        self._resolve_frontend_asset = ResolveExtensionFrontendAssetUseCase(query_gateway)
        self._sync_available = SyncAvailableExtensionsUseCase(lifecycle_gateway)
        self._sync_installed = SyncInstalledExtensionsUseCase(lifecycle_gateway)
        self._install = InstallExtensionUseCase(lifecycle_gateway)
        self._uninstall = UninstallExtensionUseCase(lifecycle_gateway)
        self._reload = ReloadExtensionUseCase(lifecycle_gateway)
        self._set_enabled = SetExtensionEnabledUseCase(lifecycle_gateway)
        self._preview_package = PreviewExtensionPackageUseCase(package_gateway)
        self._install_package = InstallExtensionPackageUseCase(package_gateway)
        self._close_callback = close_callback

    async def list_extensions(self) -> list[Extension]:
        return await self._list.execute()

    async def sync_available_extensions(self) -> list[Extension]:
        return await self._sync_available.execute()

    async def sync_installed_extensions(self) -> list[Extension]:
        return await self._sync_installed.execute()

    async def install_extension(self, name: str, version: str | None = None) -> Extension:
        return await self._install.execute(name, version=version)

    async def uninstall_extension(
        self, name: str, *, drop_extension_data: bool = False
    ) -> Extension:
        return await self._uninstall.execute(
            name, drop_extension_data=drop_extension_data
        )

    async def reload_extension(self, name: str) -> Extension:
        return await self._reload.execute(name)

    async def set_enabled(self, name: str, enabled: bool) -> Extension:
        return await self._set_enabled.execute(name, enabled=enabled)

    async def get_frontend_bundle_info(self, name: str) -> ExtensionFrontendBundle:
        return await self._get_frontend.execute(name)

    async def resolve_frontend_asset(self, name: str, asset_path: str) -> Path:
        return await self._resolve_frontend_asset.execute(name, asset_path)

    async def preview_uploaded_package(
        self, fileobj: BinaryIO, filename: str | None
    ) -> ExtensionPackagePreview:
        return await self._preview_package.execute(fileobj, filename)

    async def close(self) -> None:
        if self._close_callback is not None:
            await self._close_callback()

    async def install_uploaded_package(
        self,
        package_id: str,
        *,
        allow_downgrade: bool = False,
        allow_reinstall: bool = False,
    ) -> Extension:
        return await self._install_package.execute(
            package_id,
            allow_downgrade=allow_downgrade,
            allow_reinstall=allow_reinstall,
        )


__all__ = ["ExtensionManagementProvider"]
