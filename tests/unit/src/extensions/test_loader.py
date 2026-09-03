import sys
import types
from pathlib import Path

import pytest

from src.extensions import loader
from src.extensions.registry import RegisteredExtension
from src.types.extensions_manifest import ExtensionManifest


def test_iter_extension_roots_skips_pending_deletions(monkeypatch, tmp_path: Path) -> None:
    active_root = tmp_path / "active-extension"
    pending_root = tmp_path / "pending-extension"
    active_root.mkdir()
    pending_root.mkdir()

    monkeypatch.setattr(loader.config.EXTENSIONS, "EXTENSIONS_DATA_DIR", tmp_path)
    monkeypatch.setattr(loader, "get_pending_deletion_paths", lambda: {pending_root})

    roots = loader.iter_extension_roots()

    assert roots == [active_root]


def test_check_dvt_compatibility_allows_prerelease_dvt_when_spec_matches(monkeypatch) -> None:
    monkeypatch.setattr(loader.config.APP, "VERSION", "1.17.0rc1")
    monkeypatch.setattr(loader.config.APP, "CHANNEL", "prod")
    manifest = ExtensionManifest(name="b24", version="0.6.0", dvt_version=">=1.15.0")

    assert loader.check_dvt_compatibility(manifest) is True


def test_check_dvt_compatibility_allows_prerelease_dvt_in_dev(monkeypatch) -> None:
    monkeypatch.setattr(loader.config.APP, "VERSION", "1.17.0rc1")
    monkeypatch.setattr(loader.config.APP, "CHANNEL", "dev")
    manifest = ExtensionManifest(name="b24", version="0.6.0", dvt_version=">=1.15.0")

    assert loader.check_dvt_compatibility(manifest) is True


def test_check_dvt_compatibility_keeps_stable_dvt_in_prod(monkeypatch) -> None:
    monkeypatch.setattr(loader.config.APP, "VERSION", "1.17.0")
    monkeypatch.setattr(loader.config.APP, "CHANNEL", "prod")
    manifest = ExtensionManifest(name="b24", version="0.6.0", dvt_version=">=1.15.0")

    assert loader.check_dvt_compatibility(manifest) is True


def test_check_dvt_compatibility_rejects_invalid_spec(monkeypatch) -> None:
    monkeypatch.setattr(loader.config.APP, "VERSION", "1.17.0")
    manifest = ExtensionManifest(name="broken", version="1.0.0", dvt_version="not-a-spec")

    assert loader.check_dvt_compatibility(manifest) is False


def test_resolve_nodes_dir_uses_legacy_backend_nodes_when_omitted(tmp_path: Path) -> None:
    extension_root = tmp_path / "extension"
    legacy_nodes = extension_root / "backend" / "nodes"
    legacy_nodes.mkdir(parents=True)
    extension = RegisteredExtension(
        name="sample",
        version="1.0.0",
        root_dir=extension_root,
        manifest_path=extension_root / "pyproject.toml",
    )

    assert loader.resolve_nodes_dir_if_present(extension) == legacy_nodes.resolve()
    assert loader.backend_package_name(extension) == "backend"


def test_optional_nodes_dir_is_absent_for_gateway_only_extension(tmp_path: Path) -> None:
    extension_root = tmp_path / "extension"
    extension_root.mkdir()
    extension = RegisteredExtension(
        name="sample",
        version="1.0.0",
        backend={"gateway_entrypoint": "backend.gateway:router"},
        root_dir=extension_root,
        manifest_path=extension_root / "pyproject.toml",
    )

    assert loader.resolve_nodes_dir_if_present(extension) is None


def test_resolve_nodes_dir_rejects_escape(tmp_path: Path) -> None:
    extension_root = tmp_path / "extension"
    extension_root.mkdir()
    extension = RegisteredExtension(
        name="sample",
        version="1.0.0",
        backend={"nodes_dir": "../outside"},
        root_dir=extension_root,
        manifest_path=extension_root / "pyproject.toml",
    )

    with pytest.raises(ValueError):
        loader.resolve_nodes_dir(extension)


def test_purge_extension_modules_does_not_remove_sibling_path(tmp_path: Path) -> None:
    extension_root = tmp_path / "foo"
    sibling_root = tmp_path / "foobar"
    extension_root.mkdir()
    sibling_root.mkdir()
    sibling_file = sibling_root / "module.py"
    sibling_file.write_text("", encoding="utf-8")
    extension = RegisteredExtension(
        name="foo",
        version="1.0.0",
        root_dir=extension_root,
        manifest_path=extension_root / "pyproject.toml",
    )
    module = types.ModuleType("sibling_probe")
    module.__file__ = str(sibling_file)
    sys.modules[module.__name__] = module
    try:
        loader.purge_extension_modules(extension)
        assert sys.modules[module.__name__] is module
    finally:
        sys.modules.pop(module.__name__, None)
