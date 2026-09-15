from __future__ import annotations

from pathlib import Path
from typing import BinaryIO, Protocol

from src.modules.extension_management.domain.entities import Extension
from src.modules.extension_management.domain.value_objects import (
    ExtensionFrontendBundle,
    ExtensionPackagePreview,
)


class ExtensionQueryGateway(Protocol):
    async def get_frontend_bundle_info(self, name: str) -> ExtensionFrontendBundle: ...

    async def resolve_frontend_asset(self, name: str, asset_path: str) -> Path: ...


class ExtensionLifecycleGateway(Protocol):
    async def sync_available_extensions(self) -> list[Extension]: ...

    async def sync_installed_extensions(self) -> list[Extension]: ...

    async def install_extension(self, name: str, version: str | None = None) -> Extension: ...

    async def uninstall_extension(
        self, name: str, *, drop_extension_data: bool = False
    ) -> Extension: ...

    async def reload_extension(self, name: str) -> Extension: ...

    async def set_enabled(self, name: str, enabled: bool) -> Extension: ...


class ExtensionPackageGateway(Protocol):
    async def preview_uploaded_package(
        self, fileobj: BinaryIO, filename: str | None
    ) -> ExtensionPackagePreview: ...

    async def install_uploaded_package(
        self,
        package_id: str,
        *,
        allow_downgrade: bool = False,
        allow_reinstall: bool = False,
    ) -> Extension: ...


__all__ = [
    "ExtensionLifecycleGateway",
    "ExtensionPackageGateway",
    "ExtensionQueryGateway",
]
