from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src.enums import ExtensionDepsStatus
from src.modules.extension_management.domain.entities import ExtensionCreate
from src.modules.extension_management.domain.policies import normalize_extension_identity
from src.modules.extension_management.domain.value_objects import ExtensionManifest
from src.modules.extension_management.infra.db_models import ExtensionRecord
from src.modules.extension_management.infra.management_service import ExtensionManager
from src.modules.extension_management.infra.repositories.db import ExtensionDBManager


def test_normalize_extension_identity_uses_python_package_name_rules() -> None:
    assert normalize_extension_identity("Foo.Bar") == "foo-bar"
    assert normalize_extension_identity("foo_bar") == "foo-bar"
    assert normalize_extension_identity("foo-bar") == "foo-bar"


@pytest.mark.asyncio
async def test_upgrade_from_dvt_121_legacy_db_to_122_canonical_catalog_preserves_installed_record(
    async_test_db_session,
) -> None:
    """A 1.21 repository-name row must become the 1.22 canonical catalog row in place."""
    legacy = ExtensionRecord(
        id="dvt-121-record-id",
        name="repository-name",
        display_name="Legacy Extension",
        description="Legacy description",
        repository_url="https://git.example/legacy-download.zip",
        is_enabled=False,
        is_installed=True,
        deps_status=ExtensionDepsStatus.READY,
        current_version="1.0.0",
        last_version="1.0.0",
        install_path="/var/lib/dvt/extensions/repository-name",
        manifest_json={
            "name": "repository-name",
            "version": "1.0.0",
            "state_schema": {"license": "str"},
        },
        state_json={"license": "encrypted-legacy-license", "setting": 17},
        installed_at=datetime(2026, 8, 21, tzinfo=UTC),
    )
    async_test_db_session.add(legacy)
    await async_test_db_session.commit()

    distributor = SimpleNamespace(
        list_extensions=AsyncMock(
            return_value={
                "extensions": [
                    {
                        "name": "canonical-package",
                        "display_name": "Canonical Extension",
                        "description": "Canonical catalog description",
                        "repository_url": "https://git.example/repository-name",
                        "legacy_aliases": ["repository-name", "old_tool_name"],
                        "versions": ["1.2.0", "1.1.0"],
                    }
                ]
            }
        )
    )
    manager = ExtensionManager(async_test_db_session, distributor)

    synced = await manager.sync_available_extensions()
    rows = await manager.list_extensions()

    assert len(synced) == 1
    assert len(rows) == 1
    upgraded = rows[0]
    assert upgraded.id == "dvt-121-record-id"
    assert upgraded.name == "repository-name"
    assert upgraded.is_installed is True
    assert upgraded.is_enabled is False
    assert upgraded.current_version == "1.0.0"
    assert upgraded.install_path == "/var/lib/dvt/extensions/repository-name"
    assert upgraded.state_json == {
        "license": "encrypted-legacy-license",
        "setting": 17,
    }
    assert upgraded.manifest_json["state_schema"] == {"license": "str"}
    assert upgraded.manifest_json["package_name"] == "canonical-package"
    assert "repository-name" in upgraded.manifest_json["legacy_names"]
    assert upgraded.repository_url == "https://git.example/repository-name"
    assert upgraded.available_versions == ["1.2.0", "1.1.0"]


@pytest.mark.asyncio
async def test_upgrade_from_dvt_121_uninstalled_legacy_db_to_122_keeps_one_record(
    async_test_db_session,
) -> None:
    legacy = ExtensionRecord(
        id="dvt-121-catalog-id",
        name="repository-name",
        display_name="Legacy Catalog Entry",
        is_installed=False,
        is_enabled=True,
        manifest_json={"name": "repository-name", "version": "1.0.0"},
        state_json={},
    )
    async_test_db_session.add(legacy)
    await async_test_db_session.commit()

    distributor = SimpleNamespace(
        list_extensions=AsyncMock(
            return_value={
                "extensions": [
                    {
                        "name": "canonical-package",
                        "display_name": "Canonical Extension",
                        "description": "Catalog description",
                        "repository_url": "https://git.example/repository-name",
                        "legacy_aliases": ["repository-name"],
                        "versions": ["1.2.0"],
                    }
                ]
            }
        )
    )
    manager = ExtensionManager(async_test_db_session, distributor)

    await manager.sync_available_extensions()
    rows = await manager.list_extensions()

    assert len(rows) == 1
    assert rows[0].id == "dvt-121-catalog-id"
    assert rows[0].is_installed is False
    assert rows[0].manifest_json["package_name"] == "canonical-package"
    assert "repository-name" in rows[0].manifest_json["legacy_names"]
    assert rows[0].available_versions == ["1.2.0"]


@pytest.mark.asyncio
async def test_reconcile_existing_duplicates_preserves_installed_survivor_and_state(
    async_test_db_session,
) -> None:
    installed = ExtensionRecord(
        id="installed-id",
        name="foo_connector",
        display_name="Foo Connector",
        description="Installed description",
        is_enabled=False,
        is_installed=True,
        deps_status=ExtensionDepsStatus.READY,
        current_version="1.0.0",
        last_version="1.0.0",
        install_path="/var/lib/dvt/extensions/foo_connector",
        manifest_json={
            "name": "foo_connector",
            "package_name": "foo_connector",
            "version": "1.0.0",
            "backend": {"nodes_dir": "backend/nodes"},
            "state_schema": {"license": "str"},
        },
        state_json={"license": "encrypted-value", "setting": 42},
        error_message="old error",
        installed_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    catalog = ExtensionRecord(
        id="catalog-id",
        name="repository-name",
        display_name="Foo Connector Catalog",
        description="Catalog description",
        repository_url="https://git.example/foo-connector",
        is_enabled=True,
        is_installed=False,
        available_versions=["1.2.0", "1.1.0"],
        last_version="1.2.0",
        manifest_json={"name": "foo-connector", "package_name": "foo-connector"},
        state_json={},
    )
    async_test_db_session.add(installed)
    async_test_db_session.add(catalog)
    await async_test_db_session.commit()

    manager = ExtensionDBManager(async_test_db_session)
    reconciled = await manager.reconcile_extension_identity(
        ExtensionCreate(
            name="foo-connector",
            display_name="Foo Connector",
            description="Catalog description",
            repository_url="https://git.example/foo-connector",
        ),
        ExtensionManifest(
            name="foo-connector",
            package_name="foo-connector",
            legacy_names=("foo_connector",),
            version="1.2.0",
            display_name="Foo Connector",
            description="Catalog description",
        ),
        aliases=("foo_connector", "repository-name"),
        available_versions=["1.2.0", "1.1.0"],
    )

    rows = await manager.list_extensions()
    assert len(rows) == 1
    assert reconciled.id == "installed-id"
    assert reconciled.name == "foo_connector"
    assert reconciled.is_installed is True
    assert reconciled.is_enabled is False
    assert reconciled.current_version == "1.0.0"
    assert reconciled.install_path == "/var/lib/dvt/extensions/foo_connector"
    assert reconciled.state_json == {"license": "encrypted-value", "setting": 42}
    assert reconciled.repository_url == "https://git.example/foo-connector"
    assert reconciled.available_versions == ["1.2.0", "1.1.0"]
    assert reconciled.last_version == "1.2.0"
    assert reconciled.manifest_json["backend"] == {"nodes_dir": "backend/nodes"}
    assert reconciled.manifest_json["state_schema"] == {"license": "str"}
    assert reconciled.manifest_json["package_name"] == "foo-connector"


@pytest.mark.asyncio
async def test_reconcile_new_catalog_record_uses_canonical_name(async_test_db_session) -> None:
    manager = ExtensionDBManager(async_test_db_session)

    extension = await manager.reconcile_extension_identity(
        ExtensionCreate(
            name="Foo.Bar",
            display_name="Foo Bar",
            description="desc",
            repository_url="https://git.example/foo-bar",
        ),
        ExtensionManifest(
            name="foo-bar",
            package_name="Foo.Bar",
            version="1.0.0",
        ),
        available_versions=["1.0.0"],
    )

    assert extension.name == "foo-bar"
    assert extension.available_versions == ["1.0.0"]


@pytest.mark.asyncio
async def test_get_extension_resolves_legacy_alias_from_manifest(async_test_db_session) -> None:
    extension = ExtensionRecord(
        name="canonical-package",
        display_name="Canonical",
        manifest_json={
            "name": "canonical-package",
            "package_name": "canonical-package",
            "legacy_names": ["repository-name", "old_tool_name"],
        },
        state_json={},
    )
    async_test_db_session.add(extension)
    await async_test_db_session.commit()
    manager = ExtensionDBManager(async_test_db_session)

    assert (await manager.get_extension("repository-name")).id == extension.id
    assert (await manager.get_extension("old-tool-name")).id == extension.id


@pytest.mark.asyncio
async def test_catalog_dvtx_uninstall_and_resync_keep_single_record(
    async_test_db_session, monkeypatch, tmp_path
) -> None:
    distributor = SimpleNamespace(
        list_extensions=AsyncMock(
            return_value={
                "extensions": [
                    {
                        "name": "foo-connector",
                        "display_name": "Foo Connector",
                        "description": "Catalog description",
                        "repository_url": "https://git.example/repository-name",
                        "legacy_aliases": ["repository-name", "foo_connector"],
                        "versions": ["1.2.0", "1.1.0"],
                    }
                ]
            }
        )
    )
    manager = ExtensionManager(async_test_db_session, distributor)

    catalog_rows = await manager.sync_available_extensions()
    assert len(catalog_rows) == 1
    catalog = catalog_rows[0]
    catalog.state_json = {"license": "encrypted-value"}
    async_test_db_session.add(catalog)
    await async_test_db_session.commit()

    package_manifest = ExtensionManifest(
        name="foo-connector",
        package_name="foo-connector",
        legacy_names=("foo_connector", "repository-name"),
        version="1.2.0",
        display_name="Foo Connector",
        description="Local package",
        state_schema={"license": "str"},
    )
    staged = SimpleNamespace(
        manifest=package_manifest,
        has_wheelhouse=False,
        package_id="package-id",
    )
    manager.install_manager.get_staged_package = Mock(return_value=staged)
    install_root = tmp_path / "foo-connector"
    install_root.mkdir()

    async def fake_install(extension, staged_package, *, latest_version, offline_only):
        assert staged_package is staged
        assert offline_only is True
        return await manager.db_manager.mark_installed(
            extension,
            version=package_manifest.version,
            install_path=str(install_root),
            manifest=package_manifest,
            latest_version=latest_version,
        )

    monkeypatch.setattr(manager, "_install_staged_package", fake_install)
    installed = await manager.install_uploaded_package("package-id")

    rows = await manager.list_extensions()
    assert len(rows) == 1
    assert installed.id == catalog.id
    assert installed.is_installed is True
    assert installed.repository_url == "https://git.example/repository-name"
    assert installed.available_versions == ["1.2.0", "1.1.0"]
    assert installed.state_json == {"license": "encrypted-value"}
    assert installed.manifest_json["state_schema"] == {"license": "str"}

    monkeypatch.setattr(manager.install_manager, "uninstall", Mock())
    monkeypatch.setattr(manager, "_refresh_runtime", AsyncMock())
    uninstalled = await manager.uninstall_extension(installed.name)
    assert uninstalled.is_installed is False
    assert uninstalled.current_version is None
    assert uninstalled.install_path is None

    await manager.sync_available_extensions()
    rows = await manager.list_extensions()
    assert len(rows) == 1
    assert rows[0].id == catalog.id
    assert rows[0].is_installed is False
    assert rows[0].repository_url == "https://git.example/repository-name"
    assert rows[0].available_versions == ["1.2.0", "1.1.0"]
    assert rows[0].state_json == {"license": "encrypted-value"}
    assert rows[0].manifest_json["state_schema"] == {"license": "str"}
