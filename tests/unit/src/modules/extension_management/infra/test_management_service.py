from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src.modules.extension_management.domain.value_objects import ExtensionManifest
from src.modules.extension_management.infra import management_service as extensions_module
from src.modules.extension_management.infra.db_models import ExtensionRecord
from src.modules.extension_management.infra.management_service import ExtensionManager
from src.modules.extension_management.infra.packages import installer as install_module


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

    def fake_chmod(path: Path, mode) -> None:
        chmod_calls.append(path)

    def fake_remove(path) -> None:
        remove_calls.append(Path(path))

    def fake_rmtree(path, onexc) -> None:
        onexc(fake_remove, blocked_path, PermissionError(5, "Access denied", str(blocked_path)))

    monkeypatch.setattr(Path, "chmod", fake_chmod)
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
            "nodes": [
                {
                    "name": "SampleNode",
                    "display_name": "Sample Node",
                    "description": "Node description",
                }
            ],
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
    monkeypatch.setattr(
        manager.install_manager,
        "_remove_install_root",
        lambda path: (_ for _ in ()).throw(PermissionError()),
    )
    monkeypatch.setattr(install_module, "add_pending_deletion", fake_add_pending_deletion)
    refresh_runtime = AsyncMock()
    monkeypatch.setattr(manager, "_refresh_runtime", refresh_runtime)

    await manager.delete_extension(extension.name)

    assert pending_calls == [(extension.name, install_root)]
    assert session.deleted == [extension]
    assert session.commit_calls == 1
    refresh_runtime.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_uninstall_extension_keeps_db_record_and_clears_installation(
    monkeypatch, tmp_path: Path
) -> None:
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
    monkeypatch.setattr(manager, "get_extension_or_raise", AsyncMock(return_value=extension))
    monkeypatch.setattr(manager.db_manager, "set_runtime_error", AsyncMock(return_value=extension))
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
        await manager.uninstall_extension(extension.name, drop_extension_data=True)

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
            manifest_json={},
            name="enabled",
            install_path=str(enabled_root),
            is_installed=True,
            is_enabled=True,
        ),
        SimpleNamespace(
            manifest_json={},
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

    assert [(item.name, item.root_dir) for item in captured_specs] == [("enabled", enabled_root)]


@pytest.mark.asyncio
async def test_refresh_runtime_retries_persisted_node_runtime_error_without_strict_mode(
    monkeypatch, tmp_path: Path
) -> None:
    manager = get_mock_extension_manager(_FakeAsyncSession())
    extension_root = tmp_path / "sample-extension"
    extension_root.mkdir()
    record = SimpleNamespace(
        manifest_json={},
        name="sample-extension",
        install_path=str(extension_root),
        is_installed=True,
        is_enabled=True,
        error_message=(
            "Extension node backend validation failed: "
            "Backend package 'backend_sample' conflicts with an existing Python package"
        ),
    )
    captured_specs = []

    def fake_load(specs, **_kwargs):
        captured_specs.extend(specs)
        return SimpleNamespace(failures={}, loaded={record.name: object()})

    set_runtime_error = AsyncMock(return_value=record)
    monkeypatch.setattr(extensions_module, "load_all_extension_runtimes", fake_load)
    monkeypatch.setattr(manager.db_manager, "set_runtime_error", set_runtime_error)

    await manager._refresh_runtime(records=[record])

    assert [(item.name, item.root_dir) for item in captured_specs] == [
        (record.name, extension_root)
    ]
    set_runtime_error.assert_awaited_once_with(record, None)


@pytest.mark.asyncio
async def test_refresh_runtime_does_not_retry_non_node_error_without_strict_mode(
    monkeypatch, tmp_path: Path
) -> None:
    manager = get_mock_extension_manager(_FakeAsyncSession())
    extension_root = tmp_path / "sample-extension"
    extension_root.mkdir()
    record = SimpleNamespace(
        manifest_json={},
        name="sample-extension",
        install_path=str(extension_root),
        is_installed=True,
        is_enabled=True,
        error_message="Extension migration failed: schema upgrade failed",
    )
    captured_specs = []

    def fake_load(specs, **_kwargs):
        captured_specs.extend(specs)
        return SimpleNamespace(failures={}, loaded={})

    set_runtime_error = AsyncMock(return_value=record)
    monkeypatch.setattr(extensions_module, "load_all_extension_runtimes", fake_load)
    monkeypatch.setattr(manager.db_manager, "set_runtime_error", set_runtime_error)

    await manager._refresh_runtime(records=[record])

    assert captured_specs == []
    set_runtime_error.assert_not_awaited()


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
        manifest_json={},
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

    assert captured_kwargs["preloaded_extension_names"] == frozenset({"sample-extension"})
    gateway_runtime.swap.assert_called_once_with({"sample-extension": gateway_app})


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
        manifest_json={},
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
async def test_upsert_extension_uses_package_identity(monkeypatch) -> None:
    session = _FakeAsyncSession()
    manager = get_mock_extension_manager(session)
    data = SimpleNamespace(
        manifest_json={},
        name="custom_name",
        display_name=None,
        description=None,
        repository_url="https://example.com/repo.git",
    )

    async def fake_get_extension(name: str):
        assert name == "yandex-metrica"

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

    assert extension.name == "yandex-metrica"
    assert extension.manifest_json["name"] == "yandex-metrica"


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
        {
            "version": "1.3.0",
            "dvt_version": ">=1.0.0,<2.0.0",
            "download_url": "https://example/1.3.0.zip",
        },
        {"version": "1.2.0", "dvt_version": "*", "download_url": "https://example/1.2.0.zip"},
    ]

    compatible = ExtensionManager._filter_compatible_versions(versions)

    assert [item["version"] for item in compatible] == ["1.3.0", "1.2.0"]


def test_filter_compatible_versions_keeps_invalid_spec(monkeypatch) -> None:
    monkeypatch.setattr(extensions_module.config.APP, "VERSION", "1.4.0")

    versions = [
        {
            "version": "1.0.0",
            "dvt_version": "not-a-spec",
            "download_url": "https://example/1.0.0.zip",
        }
    ]

    compatible = ExtensionManager._filter_compatible_versions(versions)

    assert compatible == versions


def test_filter_compatible_versions_prod_skips_prerelease_extension_versions(monkeypatch) -> None:
    monkeypatch.setattr(extensions_module.config.APP, "VERSION", "1.17.0")
    monkeypatch.setattr(extensions_module.config.APP, "CHANNEL", "prod")

    versions = [
        {
            "version": "0.6.0rc3",
            "dvt_version": ">=1.15.0",
            "download_url": "https://example/0.6.0rc3.zip",
        },
        {
            "version": "0.6.0",
            "dvt_version": ">=1.15.0",
            "download_url": "https://example/0.6.0.zip",
        },
    ]

    compatible = ExtensionManager._filter_compatible_versions(versions)

    assert [item["version"] for item in compatible] == ["0.6.0"]


def test_filter_compatible_versions_dev_allows_prerelease_extension_versions(monkeypatch) -> None:
    monkeypatch.setattr(extensions_module.config.APP, "VERSION", "1.17.0")
    monkeypatch.setattr(extensions_module.config.APP, "CHANNEL", "dev")

    versions = [
        {
            "version": "0.6.0rc3",
            "dvt_version": ">=1.15.0",
            "download_url": "https://example/0.6.0rc3.zip",
        },
        {
            "version": "0.6.0",
            "dvt_version": ">=1.15.0",
            "download_url": "https://example/0.6.0.zip",
        },
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
    staged = SimpleNamespace(
        manifest=ExtensionManifest.model_validate(
            {
                "name": "sample-extension",
                "version": "1.0.0",
                "display_name": "Sample Extension",
            }
        )
    )
    manager.install_manager.stage_from_url = AsyncMock(return_value=staged)
    install_staged = AsyncMock(return_value=extension)
    monkeypatch.setattr(manager, "_install_staged_package", install_staged)
    manager.install_manager.install_requirements = AsyncMock()
    manager.install_manager.load_manifest = lambda _root: ExtensionManifest.model_validate(
        {
            "name": "sample-extension",
            "version": "1.0.0",
            "display_name": "Sample Extension",
            "description": "desc",
        }
    )
    monkeypatch.setattr(extensions_module, "check_dvt_compatibility", lambda _manifest: True)
    monkeypatch.setattr(manager.db_manager, "mark_installed", AsyncMock(return_value=extension))
    refresh_runtime = AsyncMock()
    monkeypatch.setattr(manager, "_refresh_runtime", refresh_runtime)
    manager.install_manager._broadcast_extension_deps_install = lambda _name: None

    await manager.install_extension("sample-extension", version="1.0.0")

    manager.distributor_client.list_extension_versions.assert_awaited_once_with(
        "sample-extension", dvt_version="1.4.0", dvt_channel="dev"
    )
    manager.install_manager.stage_from_url.assert_awaited_once_with("https://example/1.0.0.zip")
    install_staged.assert_awaited_once_with(
        extension,
        staged,
        latest_version="1.1.0",
        offline_only=False,
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
    monkeypatch.setattr(extensions_module.config.EXTENSIONS, "EXTENSIONS_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(manager, "get_extension_or_raise", AsyncMock(return_value=extension))
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
    manager.install_manager.stage_from_url = AsyncMock(
        side_effect=RuntimeError("download failed before replacing files")
    )
    monkeypatch.setattr(manager.install_manager, "uninstall", Mock())

    async def mark_uninstalled(item):
        item.is_installed = False
        item.install_path = None
        return item

    monkeypatch.setattr(manager.db_manager, "mark_uninstalled", mark_uninstalled)
    monkeypatch.setattr(manager.db_manager, "set_runtime_error", AsyncMock(return_value=extension))
    monkeypatch.setattr(manager, "list_extensions", AsyncMock(return_value=[extension, other]))
    refresh_runtime = AsyncMock()
    monkeypatch.setattr(manager, "_refresh_runtime", refresh_runtime)

    with pytest.raises(RuntimeError, match="download failed"):
        await manager.install_extension("sample-extension")

    refresh_runtime.assert_not_awaited()
    assert extension.is_installed is True
    assert extension.current_version == "1.0.0"
    assert extension.install_path == str(install_root)


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
    monkeypatch.setattr(manager.db_manager, "set_runtime_error", AsyncMock(return_value=extension))
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
                "extensions": [{"name": "test-ext", "versions": ["1.0.0"], "description": "desc"}]
            }
        ),
        list_extension_versions=AsyncMock(return_value={"versions": []}),
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
    reconcile = AsyncMock(return_value=fake_extension)
    monkeypatch.setattr(manager.db_manager, "reconcile_extension_identity", reconcile)

    await manager.sync_available_extensions()

    manager.distributor_client.list_extensions.assert_awaited_once_with(
        dvt_version="1.5.0", dvt_channel="prod"
    )
    manager.distributor_client.list_extension_versions.assert_not_awaited()
    reconcile.assert_awaited_once()
    manager.distributor_client.aclose.assert_not_awaited()


@pytest.mark.asyncio
async def test_sync_available_extensions_uses_manifest_name_and_removes_legacy_alias(
    monkeypatch,
) -> None:
    session = _FakeAsyncSession()
    manager = get_mock_extension_manager(session)
    monkeypatch.setattr(extensions_module.config.APP, "VERSION", "1.22.0-rc1")
    monkeypatch.setattr(extensions_module.config.APP, "CHANNEL", "dev")

    download_url = (
        "https://extensions.distribution.denvic.tech/extensions/"
        "Bitrix24%20Connector/versions/0.9.11/download"
    )
    manifest = ExtensionManifest.model_validate(
        {
            "name": "bitrix24-connector",
            "package_name": "bitrix24-connector",
            "version": "0.9.11",
            "display_name": "Bitrix 24 Connector",
            "description": "Bitrix24 Nodes",
        }
    )
    canonical = ExtensionRecord(
        id="canonical-id",
        name="bitrix24-connector",
        display_name="Bitrix 24 Connector",
        description="Bitrix24 Nodes",
        repository_url=download_url,
        is_enabled=True,
        is_installed=True,
        current_version="0.10.0",
        manifest_json=manifest.model_dump(mode="json"),
        state_json={},
    )
    _legacy = ExtensionRecord(
        id="legacy-id",
        name="Bitrix24 Connector",
        display_name="Bitrix24 Connector",
        description="Bitrix24 Nodes",
        repository_url=download_url,
        is_enabled=True,
        is_installed=False,
        manifest_json={},
        state_json={},
    )
    manager.distributor_client = SimpleNamespace(
        list_extensions=AsyncMock(
            return_value={
                "extensions": [
                    {
                        "name": "bitrix24-connector",
                        "display_name": "Bitrix 24 Connector",
                        "description": "Bitrix24 Nodes",
                        "repository_url": "https://git.example/bitrix24-connector",
                        "legacy_aliases": ["Bitrix24 Connector"],
                        "versions": ["0.9.11"],
                    }
                ]
            }
        ),
        list_extension_versions=AsyncMock(
            return_value={
                "versions": [
                    {
                        "version": "0.9.11",
                        "dvt_version": ">=1.19.2",
                        "download_url": download_url,
                    }
                ]
            }
        ),
    )
    reconcile = AsyncMock(return_value=canonical)
    monkeypatch.setattr(manager.db_manager, "reconcile_extension_identity", reconcile)

    result = await manager.sync_available_extensions()

    data, passed_manifest = reconcile.await_args.args[:2]
    assert data.name == "bitrix24-connector"
    assert data.display_name == "Bitrix 24 Connector"
    assert passed_manifest.name == "bitrix24-connector"
    assert passed_manifest.legacy_names == ("Bitrix24 Connector",)
    assert reconcile.await_args.kwargs["available_versions"] == ["0.9.11"]
    manager.distributor_client.list_extension_versions.assert_not_awaited()
    assert result == [canonical]


@pytest.mark.asyncio
async def test_install_extension_uses_distributor_catalog_name_from_repository_url(
    monkeypatch,
) -> None:
    manager = get_mock_extension_manager(_FakeAsyncSession())
    extension = ExtensionRecord(
        id="ext-id",
        name="bitrix24-connector",
        display_name="Bitrix 24 Connector",
        description="Bitrix24 Nodes",
        repository_url=(
            "https://extensions.distribution.denvic.tech/extensions/"
            "Bitrix24%20Connector/versions/0.9.11/download"
        ),
        is_enabled=True,
        is_installed=False,
        manifest_json={},
        state_json={},
    )
    download_url = extension.repository_url
    assert download_url is not None
    staged = SimpleNamespace(
        manifest=ExtensionManifest.model_validate(
            {
                "name": "bitrix24-connector",
                "package_name": "bitrix24-connector",
                "version": "0.9.11",
                "display_name": "Bitrix 24 Connector",
            }
        )
    )
    monkeypatch.setattr(extensions_module.config.APP, "VERSION", "1.22.0-rc1")
    monkeypatch.setattr(extensions_module.config.APP, "CHANNEL", "dev")
    monkeypatch.setattr(manager, "get_extension_or_raise", AsyncMock(return_value=extension))
    manager.distributor_client = SimpleNamespace(
        list_extension_versions=AsyncMock(
            return_value={
                "versions": [
                    {
                        "version": "0.9.11",
                        "dvt_version": ">=1.19.2",
                        "download_url": download_url,
                    }
                ]
            }
        )
    )
    manager.install_manager.stage_from_url = AsyncMock(return_value=staged)
    install_staged = AsyncMock(return_value=extension)
    monkeypatch.setattr(manager, "_install_staged_package", install_staged)

    await manager.install_extension(extension.name)

    manager.distributor_client.list_extension_versions.assert_awaited_once_with(
        "bitrix24-connector",
        dvt_version="1.22.0-rc1",
        dvt_channel="dev",
    )
    install_staged.assert_awaited_once_with(
        extension,
        staged,
        latest_version="0.9.11",
        offline_only=False,
    )


@pytest.mark.asyncio
async def test_install_uploaded_package_merges_uninstalled_legacy_catalog_record(
    monkeypatch,
) -> None:
    session = _FakeAsyncSession()
    manager = get_mock_extension_manager(session)
    repository_url = (
        "https://extensions.distribution.denvic.tech/extensions/"
        "Bitrix24%20Connector/versions/0.9.11/download"
    )
    legacy = ExtensionRecord(
        id="legacy-id",
        name="Bitrix24 Connector",
        display_name="Bitrix24 Connector",
        description="Bitrix24 Nodes",
        repository_url=repository_url,
        is_enabled=True,
        is_installed=False,
        last_version="0.9.11",
        available_versions=["0.9.11", "0.9.10"],
        manifest_json={},
        state_json={},
    )
    manifest = ExtensionManifest.model_validate(
        {
            "name": "bitrix24-connector",
            "package_name": "bitrix24-connector",
            "version": "0.10.0",
            "display_name": "Bitrix 24 Connector",
            "description": "Bitrix24 Nodes",
        }
    )
    staged = SimpleNamespace(manifest=manifest, has_wheelhouse=False)
    canonical = ExtensionRecord(
        id="canonical-id",
        name="bitrix24-connector",
        display_name="Bitrix 24 Connector",
        description="Bitrix24 Nodes",
        repository_url=repository_url,
        is_enabled=True,
        is_installed=False,
        manifest_json=manifest.model_dump(mode="json"),
        state_json={},
    )
    manager.install_manager.get_staged_package = Mock(return_value=staged)
    monkeypatch.setattr(extensions_module, "check_dvt_compatibility", lambda _manifest: True)
    monkeypatch.setattr(manager, "get_extension", AsyncMock(return_value=None))
    monkeypatch.setattr(manager, "list_extensions", AsyncMock(return_value=[legacy]))
    reconcile = AsyncMock(return_value=canonical)
    monkeypatch.setattr(manager.db_manager, "reconcile_extension_identity", reconcile)
    install_staged = AsyncMock(return_value=canonical)
    monkeypatch.setattr(manager, "_install_staged_package", install_staged)

    result = await manager.install_uploaded_package("package-id")

    reconcile.assert_awaited_once()
    create_data, passed_manifest = reconcile.await_args.args[:2]
    assert create_data.name == "bitrix24-connector"
    assert passed_manifest is manifest
    install_staged.assert_awaited_once_with(
        canonical,
        staged,
        latest_version="0.10.0",
        offline_only=True,
    )
    assert result is canonical


@pytest.mark.asyncio
async def test_sync_installed_extensions_merges_legacy_catalog_alias_on_startup(
    monkeypatch, tmp_path: Path
) -> None:
    session = _FakeAsyncSession()
    manager = get_mock_extension_manager(session)
    root = tmp_path / "bitrix24-connector"
    root.mkdir()
    repository_url = (
        "https://extensions.distribution.denvic.tech/extensions/"
        "Bitrix24%20Connector/versions/0.9.11/download"
    )
    manifest = ExtensionManifest.model_validate(
        {
            "name": "bitrix24-connector",
            "package_name": "bitrix24-connector",
            "version": "0.10.0",
            "display_name": "Bitrix 24 Connector",
        }
    )
    canonical = ExtensionRecord(
        id="canonical-id",
        name=manifest.name,
        display_name="Bitrix 24 Connector",
        description="",
        is_enabled=True,
        is_installed=True,
        current_version=manifest.version,
        install_path=str(root),
        manifest_json=manifest.model_dump(mode="json"),
        state_json={},
    )
    legacy = ExtensionRecord(
        id="legacy-id",
        name="Bitrix24 Connector",
        display_name="Bitrix24 Connector",
        description="",
        repository_url=repository_url,
        is_enabled=True,
        is_installed=False,
        available_versions=["0.9.11"],
        manifest_json={},
        state_json={},
    )
    monkeypatch.setattr(extensions_module, "process_pending_deletions", lambda _fn: None)
    monkeypatch.setattr(extensions_module, "iter_extension_roots", lambda: [root])
    monkeypatch.setattr(
        extensions_module, "load_manifest_payload", lambda *_args, **_kwargs: manifest
    )
    monkeypatch.setattr(
        manager.db_manager,
        "sync_installed_extensions",
        AsyncMock(return_value=[canonical, legacy]),
    )
    reconcile = AsyncMock(return_value=canonical)
    monkeypatch.setattr(manager.db_manager, "reconcile_extension_identity", reconcile)
    monkeypatch.setattr(
        manager,
        "list_extensions",
        AsyncMock(side_effect=[[canonical], [canonical]]),
    )
    refresh_runtime = AsyncMock()
    monkeypatch.setattr(manager, "_refresh_runtime", refresh_runtime)

    result = await manager.sync_installed_extensions()

    reconcile.assert_awaited_once()
    refresh_runtime.assert_awaited_once_with(records=[canonical])
    assert result == [canonical]


@pytest.mark.asyncio
async def test_find_extension_for_manifest_matches_project_package_name(monkeypatch) -> None:
    manager = get_mock_extension_manager(_FakeAsyncSession())
    legacy = ExtensionRecord(
        name="Yandex Metrica Connector",
        display_name="Yandex Metrica Connector",
        description="",
        is_installed=False,
        manifest_json={},
        state_json={},
    )
    manifest = ExtensionManifest.model_validate(
        {
            "name": "yandex_metrica",
            "package_name": "yandex-metrica-connector",
            "legacy_names": ["Yandex Metrica Connector"],
            "version": "0.1.0",
            "display_name": "Yandex Metrica",
        }
    )
    monkeypatch.setattr(manager, "list_extensions", AsyncMock(return_value=[legacy]))

    matched = await manager._find_extension_for_manifest(manifest)

    assert matched is legacy


def test_distributor_extension_name_falls_back_for_non_catalog_url() -> None:
    extension = ExtensionRecord(
        name="custom-extension",
        display_name="Custom Extension",
        description="",
        repository_url="https://example.com/custom-extension.dvtx",
        manifest_json={},
        state_json={},
    )

    assert ExtensionManager._distributor_extension_name(extension) == "custom-extension"
