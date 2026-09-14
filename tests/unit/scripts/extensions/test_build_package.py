from __future__ import annotations

import zipfile
from pathlib import Path

import scripts.extensions.build_package as build_package_module
from scripts.extensions.build_package import build_package


def test_build_package_keeps_frontend_dist_and_excludes_root_dist(tmp_path: Path) -> None:
    extension_dir = tmp_path / "sample-extension"
    frontend_dist = extension_dir / "frontend" / "dist"
    frontend_dist.mkdir(parents=True)
    (frontend_dist / "index.js").write_text("export const ok = true;", encoding="utf-8")
    root_dist = extension_dir / "dist"
    root_dist.mkdir()
    (root_dist / "old.dvtx").write_bytes(b"old")
    (extension_dir / "pyproject.toml").write_text(
        '[project]\nname = "sample-extension"\nversion = "1.2.3"\ndependencies = []\n\n'
        '[tool.dvt_extension]\nname = "sample-extension"\ndisplay_name = "Sample"\n',
        encoding="utf-8",
    )
    output = tmp_path / "output" / "sample-extension-1.2.3.dvtx"

    result = build_package(
        extension_dir,
        output=output,
        include_wheelhouse=False,
        build_frontend=False,
    )

    assert result == output.resolve()
    with zipfile.ZipFile(result) as archive:
        names = set(archive.namelist())
    assert "sample-extension-1.2.3/frontend/dist/index.js" in names
    assert "sample-extension-1.2.3/.dvt/bundle.toml" in names
    assert "sample-extension-1.2.3/dist/old.dvtx" not in names


def test_build_package_treats_output_without_dvtx_suffix_as_directory(tmp_path: Path) -> None:
    extension_dir = tmp_path / "sample-extension"
    extension_dir.mkdir()
    (extension_dir / "pyproject.toml").write_text(
        '[project]\nname = "sample-extension"\nversion = "1.2.3"\ndependencies = []\n\n'
        '[tool.dvt_extension]\nname = "sample-extension"\ndisplay_name = "Sample"\n',
        encoding="utf-8",
    )
    output_dir = tmp_path / "output"

    result = build_package(
        extension_dir,
        output=output_dir,
        include_wheelhouse=False,
        build_frontend=False,
    )

    assert result == (output_dir / "sample-extension-1.2.3.dvtx").resolve()
    assert result.is_file()


def test_build_frontend_uses_npm_ci_with_lock_even_when_node_modules_exists(
    monkeypatch, tmp_path: Path
) -> None:
    extension_dir = tmp_path / "sample-extension"
    extension_dir.mkdir()
    (extension_dir / "package.json").write_text("{}", encoding="utf-8")
    (extension_dir / "package-lock.json").write_text("{}", encoding="utf-8")
    (extension_dir / "node_modules").mkdir()
    npm_path = r"C:\\Program Files\\nodejs\\npm.cmd"
    commands: list[tuple[list[str], Path]] = []

    monkeypatch.setattr(build_package_module.shutil, "which", lambda name: npm_path if name == "npm" else None)
    monkeypatch.setattr(
        build_package_module,
        "_run",
        lambda command, cwd: commands.append((command, cwd)),
    )

    build_package_module._build_frontend(extension_dir)

    assert commands == [
        ([npm_path, "ci"], extension_dir),
        ([npm_path, "run", "build"], extension_dir),
    ]


def test_build_frontend_uses_npm_install_without_lock(monkeypatch, tmp_path: Path) -> None:
    extension_dir = tmp_path / "sample-extension"
    extension_dir.mkdir()
    (extension_dir / "package.json").write_text("{}", encoding="utf-8")
    npm_path = "npm"
    commands: list[tuple[list[str], Path]] = []

    monkeypatch.setattr(build_package_module.shutil, "which", lambda name: npm_path if name == "npm" else None)
    monkeypatch.setattr(
        build_package_module,
        "_run",
        lambda command, cwd: commands.append((command, cwd)),
    )

    build_package_module._build_frontend(extension_dir)

    assert commands == [
        ([npm_path, "install"], extension_dir),
        ([npm_path, "run", "build"], extension_dir),
    ]


def test_build_frontend_reports_missing_npm(monkeypatch, tmp_path: Path) -> None:
    extension_dir = tmp_path / "sample-extension"
    extension_dir.mkdir()
    (extension_dir / "package.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(build_package_module.shutil, "which", lambda _name: None)

    try:
        build_package_module._build_frontend(extension_dir)
    except RuntimeError as exc:
        message = str(exc)
    else:
        raise AssertionError("Expected RuntimeError when npm is not available")

    assert "npm" in message
    assert "--skip-frontend-build" in message
