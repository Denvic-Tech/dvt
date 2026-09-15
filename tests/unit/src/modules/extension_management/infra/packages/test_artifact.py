from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from src.modules.extension_management.infra.packages.artifact import (
    discard_staged_extension_package,
    stage_extension_package,
)

import config


def _package_bytes(entries: dict[str, bytes | str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, value in entries.items():
            archive.writestr(name, value)
    return buffer.getvalue()


def _bundle_metadata() -> str:
    return (
        '[bundle]\nschema_version = 1\ntype = "dvt-extension"\n\n'
        '[runtime]\nos = "linux"\narch = "x86_64"\npython = "3.13"\n'
    )


def _manifest(*, version: str = "1.0.0", dependencies: str = "") -> str:
    return (
        '[project]\nname = "sample-extension"\n'
        f'version = "{version}"\n'
        f"dependencies = [{dependencies}]\n\n"
        "[tool.dvt_extension]\n"
        'name = "sample-extension"\n'
        'display_name = "Sample Extension"\n'
        'dvt_version = ">=1.0"\n'
    )


def test_stage_dvtx_reads_manifest_and_wheelhouse(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(config.EXTENSIONS, "EXTENSIONS_DATA_DIR", str(tmp_path / "extensions"))
    content = _package_bytes(
        {
            "sample-extension/pyproject.toml": _manifest(dependencies='"demo-dep==1.0"'),
            "sample-extension/.dvt/bundle.toml": _bundle_metadata(),
            "sample-extension/.dvt/wheels/demo_dep-1.0-py3-none-any.whl": b"wheel",
            "sample-extension/backend/__init__.py": "",
        }
    )

    staged = stage_extension_package(io.BytesIO(content), "sample-extension.dvtx")
    try:
        assert staged.manifest.name == "sample-extension"
        assert staged.manifest.version == "1.0.0"
        assert staged.has_wheelhouse is True
        assert staged.bundled_wheels_count == 1
    finally:
        discard_staged_extension_package(staged.package_id)


def test_stage_legacy_zip_is_supported(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(config.EXTENSIONS, "EXTENSIONS_DATA_DIR", str(tmp_path / "extensions"))
    content = _package_bytes({"pyproject.toml": _manifest()})

    staged = stage_extension_package(io.BytesIO(content), "sample-extension.zip")
    try:
        assert staged.manifest.name == "sample-extension"
    finally:
        discard_staged_extension_package(staged.package_id)


def test_stage_package_rejects_path_traversal(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(config.EXTENSIONS, "EXTENSIONS_DATA_DIR", str(tmp_path / "extensions"))
    content = _package_bytes(
        {
            "pyproject.toml": _manifest(),
            ".dvt/bundle.toml": _bundle_metadata(),
            "../escape.txt": "bad",
        }
    )

    with pytest.raises(ValueError, match="Unsafe archive path"):
        stage_extension_package(io.BytesIO(content), "sample-extension.dvtx")

    assert not (tmp_path / "escape.txt").exists()


def test_stage_package_rejects_unknown_suffix(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(config.EXTENSIONS, "EXTENSIONS_DATA_DIR", str(tmp_path / "extensions"))
    content = _package_bytes({"pyproject.toml": _manifest()})

    with pytest.raises(ValueError, match=r"Only \.dvtx and \.zip"):
        stage_extension_package(io.BytesIO(content), "sample-extension.tar.gz")
