from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src.extensions.manifest import ExtensionManifest
from src.managers import (
    extension_install_manager as install_module,
    extension_manager as extensions_module,
)
from src.managers.extension_manager import ExtensionManager
from src.models.extension import ExtensionRecord


def get_mock_extension_manager(session=None):
    manager = ExtensionManager(session=session, distributor_client=None)
    manager.migration_manager = Mock()
    return manager

def test_remove_install_root_retries_readonly_path(monkeypatch, tmp_path: Path) -> None:
    install_root = tmp_path / "sample-extension"
    install_root.mkdir()
    blocked_path = install_root / "blocked.idx"
    blocked_path.write_text("content", encoding="utf-8")

    chmod_calls: list[Path] = []
    remove_calls: list[Path] = []

    def fake_chmod(path, mode) -> None:
        chmod_calls.append(Path(path))

    def fake_remove(path) -> None:
        remove_calls.append(Path(path))

    def fake_rmtree(path, onexc) -> None:
        onexc(fake_remove, blocked_path, PermissionError(5, "Access denied", str(blocked_path)))

    monkeypatch.setattr(install_module.os, "chmod", fake_chmod)
    monkeypatch.setattr(install_module, "shutil", SimpleNamespace(rmtree=fake_rmtree))

    get_mock_extension_manager()._remove_install_root(install_root)

    assert chmod_calls == [blocked_path]
    assert remove_calls == [blocked_path]


def test_remove_install_root_reraises_non_permission_errors(monkeypatch, tmp_path: Path) -> None:
    install_root = tmp_path / "sample-extension"
    install_root.mkdir()
    blocked_path = install_root / "blocked.idx"
    blocked_path.write_text("content", encoding="utf-8")

    def fake_rmtree(path, onexc) -> None:
        onexc(Path.unlink, blocked_path, FileNotFoundError(str(blocked_path)))

    monkeypatch.setattr(install_module, "shutil", SimpleNamespace(rmtree=fake_rmtree))

    with pytest.raises(FileNotFoundError):
        get_mock_extension_manager()._remove_install_root(install_root)


def test_build_manifest_json_preserves_known_manifest_fields() -> None:
    manifest_json = ExtensionManager._build_manifest_json(
        name="sample-extension",
        display_name="Sample Extension",
        description="Short description",
        repository_url="https://example.com/repo.git",
        existing_manifest={
            "version": "1.2.3",
            "requirements": ["numpy"],
            "state_schema": {"foo": "str"},
            "nodes": [{"name": "SampleNode", "display_name": "Sample Node", "description": "Node description"}],
        },
    )

    assert manifest_json["name"] == "sample-extension"
    assert manifest_json["version"] == "1.2.3"
    assert manifest_json["repository_url"] == "https://example.com/repo.git"
    assert manifest_json["requirements"] == ["numpy"]
    assert manifest_json["state_schema"] == {"foo": "str"}
    assert manifest_json["nodes"] == [
        {
            "name": "SampleNode",
            "display_name": "Sample Node",
            "description": "Node description",
        }
    ]


class _FakeAsyncSession:
    def __init__(self) -> None:
        self.deleted = []
        self.commit_calls = 0
        self.added = []
        self.refreshed = []

    async def delete(self, instance) -> None:
        self.deleted.append(instance)

    async def commit(self) -> None:
        self.commit_calls += 1

    def add(self, instance) -> None:
        self.added.append(instance)

    async def refresh(self, instance) -> None:
        self.refreshed.append(instance)

    async def merge(self, instance):
        for idx, existing in enumerate(self.added):
            if getattr(existing, "name", None) == getattr(instance, "name", None):
                self.added[idx] = instance
                return instance

        self.added.append(instance)
        return instance


@pytest.mark.asyncio
async def test_delete_extension_defers_locked_directory(monkeypatch, tmp_path: Path) -> None:
    install_root = tmp_path / "sample-extension"
    install_root.mkdir()
    extension = SimpleNamespace(name="sample-extension", install_path=str(install_root))
    session = _FakeAsyncSession()
    pending_calls: list[tuple[str, Path]] = []

    manager = get_mock_extension_manager(session)

    async def fake_get_extension_or_raise(name: str):
        assert name == extension.name
        return extension

    def fake_add_pending_deletion(name: str, path: Path) -> None:
        pending_calls.append((name, path))

    monkeypatch.setattr(manager, "get_extension_or_raise", fake_get_extension_or_raise)
    monkeypatch.setattr(manager.install_manager, "_remove_install_root", lambda path: (_ for _ in ()).throw(PermissionError()))
    monkeypatch.setattr(install_module, "add_pending_deletion", fake_add_pending_deletion)
    refresh_runtime = AsyncMock()
    monkeypatch.setattr(manager, "_refresh_runtime", refresh_runtime)

    await manager.delete_extension(extension.name)

    assert pending_calls == [(extension.name, install_root)]
    assert session.deleted == [extension]
    assert session.commit_calls == 1
    refresh_runtime.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_uninstall_extension_keeps_db_record_and_clears_installation(monkeypatch, tmp_path: Path) -> None:
    install_root = tmp_path / "sample-extension"
    install_root.mkdir()
    extension = ExtensionRecord(
        id="ext-id",
        name="sample-extension",
        display_name="Sample Extension",
        description="",
        repository_url="https://example.com/repo.git",
        is_enabled=True,
        is_installed=True,
        current_version="1.0.0",
        install_path=str(install_root),
        manifest_json={},
        state_json={},
    )
    session = _FakeAsyncSession()
    manager = get_mock_extension_manager(session)

    async def fake_get_extension_or_raise(name: str):
        assert name == extension.name
        return extension

    monkeypatch.setattr(manager, "get_extension_or_raise", fake_get_extension_or_raise)
    monkeypatch.setattr(manager, "list_extensions", AsyncMock(return_value=[extension]))
    monkeypatch.setattr(manager.install_manager, "_remove_install_root", lambda path: None)
    refresh_runtime = AsyncMock()
    monkeypatch.setattr(manager, "_refresh_runtime", refresh_runtime)

    updated = await manager.uninstall_extension(extension.name)

    assert updated is extension
    assert extension.is_installed is False
    assert extension.install_path is None
    assert extension.current_version is None
    assert session.deleted == []
    assert session.commit_calls == 1
    assert refresh_runtime.await_count == 2
    first_call, second_call = refresh_runtime.await_args_list
    assert first_call.kwargs == {"records": []}
    assert second_call.kwargs == {}


@pytest.mark.asyncio
async def test_uninstall_drop_failure_keeps_runtime_files_and_install_record(
    monkeypatch, tmp_path: Path
) -> None:
    install_root = tmp_path / "sample-extension"
    install_root.mkdir()
    extension = ExtensionRecord(
        id="ext-id",
        name="sample-extension",
        display_name="Sample Extension",
        description="",
        is_enabled=True,
        is_installed=True,
        current_version="1.0.0",
        install_path=str(install_root),
        manifest_json={},
        state_json={},
    )
    manager = get_mock_extension_manager(_FakeAsyncSession())
    monkeypatch.setattr(
        manager, "get_extension_or_raise", AsyncMock(return_value=extension)
    )
    monkeypatch.setattr(
        manager.db_manager, "set_runtime_error", AsyncMock(return_value=extension)
    )
    monkeypatch.setattr(
        manager.migration_manager,
        "drop_schema",
        lambda _name: (_ for _ in ()).throw(RuntimeError("drop denied")),
    )
    uninstall = Mock()
    monkeypatch.setattr(manager.install_manager, "uninstall", uninstall)
    refresh_runtime = AsyncMock()
    monkeypatch.setattr(manager, "_refresh_runtime", refresh_runtime)

    with pytest.raises(RuntimeError, match="Extension data removal failed"):
        await manager.uninstall_extension(
            extension.name, drop_extension_data=True
        )

    assert extension.is_installed is True
    assert extension.install_path == str(install_root)
    assert install_root.exists()
    uninstall.assert_not_called()
    refresh_runtime.assert_not_awaited()


@pytest.mark.asyncio
async def test_refresh_runtime_excludes_disabled_extensions(monkeypatch, tmp_path: Path) -> None:
    manager = get_mock_extension_manager(_FakeAsyncSession())
    enabled_root = tmp_path / "enabled"
    disabled_root = tmp_path / "disabled"
    enabled_root.mkdir()
    disabled_root.mkdir()
    records = [
        SimpleNamespace(
            name="enabled",
            install_path=str(enabled_root),
            is_installed=True,
            is_enabled=True,
        ),
        SimpleNamespace(
            name="disabled",
            install_path=str(disabled_root),
            is_installed=True,
            is_enabled=False,
        ),
    ]
    captured_specs = []

    def fake_load(specs, **_kwargs):
        captured_specs.extend(specs)
        return SimpleNamespace(failures={}, loaded={"enabled": object()})

    monkeypatch.setattr(extensions_module, "load_all_extension_runtimes", fake_load)

    await manager._refresh_runtime(records=records)

    assert [(item.name, item.root_dir) for item in captured_specs] == [
        ("enabled", enabled_root)
    ]


@pytest.mark.asyncio
async def test_gateway_refresh_reuses_preloaded_extension_module_generation(
    monkeypatch, tmp_path: Path
) -> None:
    manager = ExtensionManager(
        session=_FakeAsyncSession(),
        distributor_client=None,
        gateway_runtime=True,
    )
    extension_root = tmp_path / "sample-extension"
    extension_root.mkdir()
    record = SimpleNamespace(
        name="sample-extension",
        install_path=str(extension_root),
        is_installed=True,
        is_enabled=True,
        error_message=None,
    )
    gateway_app = object()
    captured_kwargs = {}

    monkeypatch.setattr(
        extensions_module,
        "prepare_extension_gateway_runtime",
        lambda _specs: SimpleNamespace(
            failures={},
            apps={"sample-extension": gateway_app},
        ),
    )

    def fake_load(_specs, **kwargs):
        captured_kwargs.update(kwargs)
        return SimpleNamespace(failures={}, loaded={"sample-extension": object()})

    monkeypatch.setattr(extensions_module, "load_all_extension_runtimes", fake_load)
    gateway_runtime = SimpleNamespace(swap=Mock())
    monkeypatch.setattr(
        extensions_module,
        "get_extension_gateway_runtime",
        lambda: gateway_runtime,
    )

    await manager._refresh_runtime(records=[record])

    assert captured_kwargs["preloaded_extension_names"] == frozenset(
        {"sample-extension"}
    )
    gateway_runtime.swap.assert_called_once_with(
        {"sample-extension": gateway_app}
    )


@pytest.mark.asyncio
async def test_set_enabled_rolls_back_db_state_when_runtime_refresh_fails(
    monkeypatch,
) -> None:
    manager = get_mock_extension_manager()
    previous = SimpleNamespace(name="sample", is_enabled=False)
    enabled = SimpleNamespace(name="sample", is_enabled=True)
    get_extension = AsyncMock(return_value=previous)
    set_enabled = AsyncMock(side_effect=[enabled, previous])
    refresh_runtime = AsyncMock(side_effect=RuntimeError("broken extension"))
    monkeypatch.setattr(manager, "get_extension_or_raise", get_extension)
    monkeypatch.setattr(manager.db_manager, "set_enabled", set_enabled)
    monkeypatch.setattr(manager, "_refresh_runtime", refresh_runtime)

    with pytest.raises(RuntimeError, match="broken extension"):
        await manager.set_enabled("sample", True)

    assert set_enabled.await_args_list[0].args == ("sample", True)
    assert set_enabled.await_args_list[1].args == ("sample", False)


@pytest.mark.asyncio
async def test_upsert_extension_loads_manifest_from_repository(monkeypatch) -> None:
    session = _FakeAsyncSession()
    manager = get_mock_extension_manager(session)
    data = SimpleNamespace(
        name="yandex_metrica",
        display_name=None,
        description=None,
        repository_url="https://example.com/repo.git",
    )

    monkeypatch.setattr(manager, "get_extension", AsyncMock(return_value=None))
    monkeypatch.setattr(manager.db_manager, "get_extension", AsyncMock(return_value=None))
    monkeypatch.setattr(
        manager,
        "_load_manifest_from_repository",
        AsyncMock(
            return_value=ExtensionManifest.model_validate(
                {
                    "name": "yandex_metrica",
                    "version": "0.1.0",
                    "display_name": "Yandex Metrica",
                    "description": "Yandex Metrica nodes for DVT",
                    "repository_url": "https://example.com/repo.git",
                    "nodes": [
                        {
                            "name": "ReadYandexMetricaReports",
                            "display_name": "Read Yandex Metrica Reports",
                            "description": "Loads report data from the Yandex Metrica Reporting API.",
                        }
                    ],
                }
            ),
        ),
    )

    extension = await manager.upsert_extension(data)

    assert extension.display_name == "Yandex Metrica"
    assert extension.description == "Yandex Metrica nodes for DVT"
    assert extension.manifest_json["nodes"] == [
        {
            "name": "ReadYandexMetricaReports",
            "display_name": "Read Yandex Metrica Reports",
            "description": "Loads report data from the Yandex Metrica Reporting API.",
        }
    ]


@pytest.mark.asyncio
async def test_upsert_extension_keeps_requested_extension_name(monkeypatch) -> None:
    session = _FakeAsyncSession()
    manager = get_mock_extension_manager(session)
    data = SimpleNamespace(
        name="custom_name",
        display_name=None,
        description=None,
        repository_url="https://example.com/repo.git",
    )

    async def fake_get_extension(name: str):
        assert name == "custom_name"

    monkeypatch.setattr(manager, "get_extension", fake_get_extension)
    monkeypatch.setattr(manager.db_manager, "get_extension", fake_get_extension)
    monkeypatch.setattr(
        manager,
        "_load_manifest_from_repository",
        AsyncMock(
            return_value=ExtensionManifest.model_validate(
                {
                    "name": "yandex_metrica",
                    "version": "0.1.0",
                    "display_name": "Yandex Metrica",
                    "description": "Yandex Metrica nodes for DVT",
                    "repository_url": "https://example.com/repo.git",
                }
            ),
        ),
    )

    extension = await manager.upsert_extension(data)

    assert extension.name == "custom_name"
    assert extension.manifest_json["name"] == "custom_name"


def test_find_known_extension_for_manifest_ignores_repository_url(tmp_path: Path) -> None:
    manifest = ExtensionManifest.model_validate(
        {
            "name": "yandex_metrica",
            "version": "0.1.0",
            "repository_url": "https://example.com/repo.git",
        }
    )
    known = {
        "custom_name": ExtensionRecord(
            name="custom_name",
            display_name="Custom",
            description="",
            repository_url="https://example.com/repo.git",
            is_enabled=True,
            is_installed=False,
            manifest_json={},
            state_json={},
        )
    }

    matched = ExtensionManager._find_known_extension_for_manifest(
        known=known,
        manifest=manifest,
        root_dir=tmp_path / "yandex_metrica",
    )

    assert matched is None


def test_filter_compatible_versions_filters_by_dvt_version(monkeypatch) -> None:
    monkeypatch.setattr(extensions_module.config.APP, "VERSION", "1.4.0")

    versions = [
        {"version": "2.0.0", "dvt_version": ">=2.0.0", "download_url": "https://example/2.0.0.zip"},
        {"version": "1.3.0", "dvt_version": ">=1.0.0,<2.0.0", "download_url": "https://example/1.3.0.zip"},
        {"version": "1.2.0", "dvt_version": "*", "download_url": "https://example/1.2.0.zip"},
    ]

    compatible = ExtensionManager._filter_compatible_versions(versions)

    assert [item["version"] for item in compatible] == ["1.3.0", "1.2.0"]


def test_filter_compatible_versions_keeps_invalid_spec(monkeypatch) -> None:
    monkeypatch.setattr(extensions_module.config.APP, "VERSION", "1.4.0")

    versions = [{"version": "1.0.0", "dvt_version": "not-a-spec", "download_url": "https://example/1.0.0.zip"}]

    compatible = ExtensionManager._filter_compatible_versions(versions)

    assert compatible == versions


def test_filter_compatible_versions_prod_skips_prerelease_extension_versions(monkeypatch) -> None:
    monkeypatch.setattr(extensions_module.config.APP, "VERSION", "1.17.0")
    monkeypatch.setattr(extensions_module.config.APP, "CHANNEL", "prod")

    versions = [
        {"version": "0.6.0rc3", "dvt_version": ">=1.15.0", "download_url": "https://example/0.6.0rc3.zip"},
        {"version": "0.6.0", "dvt_version": ">=1.15.0", "download_url": "https://example/0.6.0.zip"},
    ]

    compatible = ExtensionManager._filter_compatible_versions(versions)

    assert [item["version"] for item in compatible] == ["0.6.0"]


def test_filter_compatible_versions_dev_allows_prerelease_extension_versions(monkeypatch) -> None:
    monkeypatch.setattr(extensions_module.config.APP, "VERSION", "1.17.0")
    monkeypatch.setattr(extensions_module.config.APP, "CHANNEL", "dev")

    versions = [
        {"version": "0.6.0rc3", "dvt_version": ">=1.15.0", "download_url": "https://example/0.6.0rc3.zip"},
        {"version": "0.6.0", "dvt_version": ">=1.15.0", "download_url": "https://example/0.6.0.zip"},
    ]

    compatible = ExtensionManager._filter_compatible_versions(versions)

    assert [item["version"] for item in compatible] == ["0.6.0rc3", "0.6.0"]


@pytest.mark.asyncio
async def test_install_extension_uses_selected_version(monkeypatch, tmp_path: Path) -> None:
    session = _FakeAsyncSession()
    manager = get_mock_extension_manager(session)
    extension = ExtensionRecord(
        id="ext-id",
        name="sample-extension",
        display_name="Sample Extension",
        description="",
        repository_url=None,
        is_enabled=True,
        is_installed=False,
        install_path=None,
        manifest_json={},
        state_json={},
    )

    monkeypatch.setattr(extensions_module.config.APP, "VERSION", "1.4.0")
    monkeypatch.setattr(extensions_module.config.APP, "CHANNEL", "dev")
    monkeypatch.setattr(extensions_module.config.EXTENSIONS, "EXTENSIONS_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(manager, "get_extension_or_raise", AsyncMock(return_value=extension))
    manager.distributor_client = SimpleNamespace(
        list_extension_versions=AsyncMock(
            return_value={
                "versions": [
                    {
                        "version": "1.1.0",
                        "dvt_version": ">=1.0.0,<2.0.0",
                        "download_url": "https://example/1.1.0.zip",
                    },
                    {
                        "version": "1.0.0",
                        "dvt_version": ">=1.0.0,<2.0.0",
                        "download_url": "https://example/1.0.0.zip",
                    },
                ]
            }
        )
    )
    manager.install_manager.install_from_url = AsyncMock()
    manager.install_manager.install_requirements = AsyncMock()
    manager.install_manager.load_manifest = lambda _root: ExtensionManifest.model_validate(
        {
            "name": "sample-extension",
            "version": "1.0.0",
            "display_name": "Sample Extension",
            "description": "desc",
        }
    )
    monkeypatch.setattr("src.extensions.loader.check_dvt_compatibility", lambda _manifest: True)
    monkeypatch.setattr(manager.db_manager, "mark_installed", AsyncMock(return_value=extension))
    refresh_runtime = AsyncMock()
    monkeypatch.setattr(manager, "_refresh_runtime", refresh_runtime)
    manager.install_manager._broadcast_extension_deps_install = lambda _name: None

    await manager.install_extension("sample-extension", version="1.0.0")

    manager.distributor_client.list_extension_versions.assert_awaited_once_with(
        "sample-extension", dvt_version="1.4.0", dvt_channel="dev"
    )
    manager.install_manager.install_from_url.assert_awaited_once()
    assert manager.install_manager.install_from_url.await_args.args[0] == "https://example/1.0.0.zip"
    manager.db_manager.mark_installed.assert_awaited_once()
    assert manager.db_manager.mark_installed.await_args.kwargs["latest_version"] == "1.1.0"
    manager.migration_manager.upgrade.assert_called_once()
    refresh_runtime.assert_awaited_once_with(
        strict_names=frozenset({"sample-extension"})
    )


@pytest.mark.asyncio
async def test_failed_install_deactivates_previous_runtime(monkeypatch, tmp_path: Path) -> None:
    manager = get_mock_extension_manager(_FakeAsyncSession())
    install_root = tmp_path / "sample-extension"
    install_root.mkdir()
    extension = ExtensionRecord(
        id="ext-id",
        name="sample-extension",
        display_name="Sample Extension",
        description="",
        is_enabled=True,
        is_installed=True,
        current_version="1.0.0",
        install_path=str(install_root),
        manifest_json={},
        state_json={},
    )
    other = SimpleNamespace(name="other-extension")

    monkeypatch.setattr(extensions_module.config.APP, "VERSION", "1.4.0")
    monkeypatch.setattr(extensions_module.config.APP, "CHANNEL", "dev")
    monkeypatch.setattr(
        extensions_module.config.EXTENSIONS, "EXTENSIONS_DATA_DIR", str(tmp_path)
    )
    monkeypatch.setattr(
        manager, "get_extension_or_raise", AsyncMock(return_value=extension)
    )
    manager.distributor_client = SimpleNamespace(
        list_extension_versions=AsyncMock(
            return_value={
                "versions": [
                    {
                        "version": "2.0.0",
                        "dvt_version": "*",
                        "download_url": "https://example/2.0.0.zip",
                    }
                ]
            }
        )
    )
    manager.install_manager.install_from_url = AsyncMock(
        side_effect=RuntimeError("download failed after replacing files")
    )
    monkeypatch.setattr(manager.install_manager, "uninstall", Mock())

    async def mark_uninstalled(item):
        item.is_installed = False
        item.install_path = None
        return item

    monkeypatch.setattr(manager.db_manager, "mark_uninstalled", mark_uninstalled)
    monkeypatch.setattr(
        manager.db_manager, "set_runtime_error", AsyncMock(return_value=extension)
    )
    monkeypatch.setattr(
        manager, "list_extensions", AsyncMock(return_value=[extension, other])
    )
    refresh_runtime = AsyncMock()
    monkeypatch.setattr(manager, "_refresh_runtime", refresh_runtime)

    with pytest.raises(RuntimeError, match="download failed"):
        await manager.install_extension("sample-extension")

    refresh_runtime.assert_awaited_once()
    assert refresh_runtime.await_args.kwargs["records"] == [other]


@pytest.mark.asyncio
async def test_reload_migration_failure_deactivates_existing_runtime(
    monkeypatch, tmp_path: Path
) -> None:
    manager = get_mock_extension_manager(_FakeAsyncSession())
    install_root = tmp_path / "sample-extension"
    install_root.mkdir()
    extension = ExtensionRecord(
        id="ext-id",
        name="sample-extension",
        display_name="Sample Extension",
        description="",
        is_enabled=True,
        is_installed=True,
        current_version="1.0.0",
        install_path=str(install_root),
        manifest_json={},
        state_json={},
    )
    manifest = ExtensionManifest.model_validate(
        {"name": extension.name, "version": extension.current_version}
    )
    monkeypatch.setattr(manager, "get_extension_or_raise", AsyncMock(return_value=extension))
    manager.distributor_client = SimpleNamespace(
        list_extension_versions=AsyncMock(
            return_value={"versions": [{"version": "1.0.0", "dvt_version": "*"}]}
        )
    )
    monkeypatch.setattr(extensions_module, "load_manifest", lambda *_args, **_kwargs: manifest)
    monkeypatch.setattr(
        manager.migration_manager,
        "upgrade",
        lambda _manifest: (_ for _ in ()).throw(RuntimeError("broken migration")),
    )
    monkeypatch.setattr(
        manager.db_manager, "set_runtime_error", AsyncMock(return_value=extension)
    )
    monkeypatch.setattr(manager, "list_extensions", AsyncMock(return_value=[extension]))
    refresh_runtime = AsyncMock()
    monkeypatch.setattr(manager, "_refresh_runtime", refresh_runtime)

    with pytest.raises(RuntimeError, match="Extension migration failed"):
        await manager.reload_extension(extension.name)

    refresh_runtime.assert_awaited_once()
    assert refresh_runtime.await_args.kwargs["records"] == []


@pytest.mark.asyncio
async def test_install_extension_raises_for_incompatible_requested_version(monkeypatch) -> None:
    session = _FakeAsyncSession()
    manager = get_mock_extension_manager(session)
    extension = ExtensionRecord(
        id="ext-id",
        name="sample-extension",
        display_name="Sample Extension",
        description="",
        repository_url=None,
        is_enabled=True,
        is_installed=False,
        install_path=None,
        manifest_json={},
        state_json={},
    )

    monkeypatch.setattr(extensions_module.config.APP, "VERSION", "1.4.0")
    monkeypatch.setattr(extensions_module.config.APP, "CHANNEL", "dev")
    monkeypatch.setattr(manager, "get_extension_or_raise", AsyncMock(return_value=extension))
    manager.distributor_client = SimpleNamespace(
        list_extension_versions=AsyncMock(
            return_value={
                "versions": [
                    {
                        "version": "2.0.0",
                        "dvt_version": ">=2.0.0",
                        "download_url": "https://example/2.0.0.zip",
                    }
                ]
            }
        )
    )

    with pytest.raises(ValueError, match="No compatible version"):
        await manager.install_extension("sample-extension", version="2.0.0")

    manager.distributor_client.list_extension_versions.assert_awaited_once_with(
        "sample-extension", dvt_version="1.4.0", dvt_channel="dev"
    )


@pytest.mark.asyncio
async def test_sync_available_extensions_passes_dvt_channel(monkeypatch) -> None:
    session = _FakeAsyncSession()
    manager = get_mock_extension_manager(session)

    monkeypatch.setattr(extensions_module.config.APP, "VERSION", "1.5.0")
    monkeypatch.setattr(extensions_module.config.APP, "CHANNEL", "prod")

    manager.distributor_client = SimpleNamespace(
        list_extensions=AsyncMock(
            return_value={
                "extensions": [
                    {"name": "test-ext", "versions": ["1.0.0"], "description": "desc"}
                ]
            }
        ),
        list_extension_versions=AsyncMock(
            return_value={"versions": []}
        ),
        aclose=AsyncMock(),
    )

    fake_extension = ExtensionRecord(
        name="test-ext",
        display_name="test-ext",
        description="desc",
        repository_url=None,
        is_enabled=True,
        is_installed=False,
        manifest_json={},
        state_json={},
    )
    monkeypatch.setattr(manager, "upsert_extension", AsyncMock(return_value=fake_extension))

    await manager.sync_available_extensions()

    manager.distributor_client.list_extensions.assert_awaited_once_with(
        dvt_version="1.5.0", dvt_channel="prod"
    )
    manager.distributor_client.list_extension_versions.assert_awaited_once_with(
        "test-ext", dvt_version="1.5.0", dvt_channel="prod"
    )
