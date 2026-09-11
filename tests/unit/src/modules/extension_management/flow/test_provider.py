from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from src.modules.extension_management.domain.entities import Extension
from src.modules.extension_management.domain.value_objects import ExtensionFrontendBundle
from src.modules.extension_management.flow.providers import ExtensionManagementProvider


class _Repository:
    def __init__(self, extensions: list[Extension]) -> None:
        self._extensions = extensions

    async def list(self) -> list[Extension]:
        return list(self._extensions)

    async def get(self, name: str) -> Extension | None:
        return next((item for item in self._extensions if item.name == name), None)


class _Gateway:
    def __init__(self, extension: Extension) -> None:
        self.extension = extension
        self.install_calls: list[tuple[str, str | None]] = []

    async def get_frontend_bundle_info(self, name: str) -> ExtensionFrontendBundle:
        return ExtensionFrontendBundle(
            bundle_path=Path(f"/{name}/index.js"),
            assets_root=Path(f"/{name}"),
            entry_file="index.js",
            entrypoint=None,
        )

    async def resolve_frontend_asset(self, name: str, asset_path: str) -> Path:
        return Path(f"/{name}/{asset_path}")

    async def sync_available_extensions(self) -> list[Extension]:
        return [self.extension]

    async def sync_installed_extensions(self) -> list[Extension]:
        return [self.extension]

    async def install_extension(self, name: str, version: str | None = None) -> Extension:
        self.install_calls.append((name, version))
        return self.extension

    async def uninstall_extension(
        self, name: str, *, drop_extension_data: bool = False
    ) -> Extension:
        return self.extension

    async def reload_extension(self, name: str) -> Extension:
        return self.extension

    async def set_enabled(self, name: str, enabled: bool) -> Extension:
        return self.extension

    async def preview_uploaded_package(self, fileobj, filename):
        raise NotImplementedError

    async def install_uploaded_package(
        self,
        package_id: str,
        *,
        allow_downgrade: bool = False,
        allow_reinstall: bool = False,
    ) -> Extension:
        return self.extension


@pytest.mark.asyncio
async def test_provider_uses_repository_for_list_and_lifecycle_gateway_for_install() -> None:
    extension = Extension(name="sample", display_name="Sample")
    repository = _Repository([extension])
    gateway = _Gateway(extension)
    close = AsyncMock()
    provider = ExtensionManagementProvider(
        repository=repository,
        query_gateway=gateway,
        lifecycle_gateway=gateway,
        package_gateway=gateway,
        close_callback=close,
    )

    assert await provider.list_extensions() == [extension]
    assert await provider.install_extension("sample", version="1.2.3") is extension
    assert gateway.install_calls == [("sample", "1.2.3")]

    await provider.close()
    close.assert_awaited_once_with()
