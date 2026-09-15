from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from pathlib import Path

EXCLUDED_NAMES = {
    ".git",
    ".idea",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".venv",
    ".venv3.13",
    "node_modules",
    "tmp",
    "build",
    "__pycache__",
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a self-contained DVT extension package (.dvtx)."
    )
    parser.add_argument("extension_dir", type=Path)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument(
        "--skip-wheelhouse",
        action="store_true",
        help="Do not download Python dependencies into .dvt/wheels.",
    )
    parser.add_argument(
        "--skip-frontend-build",
        action="store_true",
        help="Do not run npm build when package.json exists.",
    )
    return parser.parse_args(argv)


def _load_project(extension_dir: Path) -> tuple[str, str, list[str]]:
    pyproject = extension_dir / "pyproject.toml"
    if not pyproject.is_file():
        raise ValueError(f"pyproject.toml not found in {extension_dir}")
    payload = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    project = payload.get("project") or {}
    tool = (payload.get("tool") or {}).get("dvt_extension") or {}
    if not tool:
        raise ValueError("[tool.dvt_extension] is required")
    name = str(tool.get("name") or project.get("name") or "").strip()
    version = str(project.get("version") or "").strip()
    dependencies = project.get("dependencies") or []
    if not name or not version:
        raise ValueError("Extension name and project version are required")
    if not isinstance(dependencies, list) or not all(isinstance(item, str) for item in dependencies):
        raise TypeError("[project].dependencies must be a list of strings")
    return name, version, dependencies


def _run(command: list[str], cwd: Path) -> None:
    completed = subprocess.run(command, cwd=cwd, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"Command failed ({completed.returncode}): {' '.join(command)}")


def _resolve_executable(name: str) -> str:
    executable = shutil.which(name)
    if executable is None:
        raise RuntimeError(
            f"Required executable '{name}' was not found in PATH. "
            "Install Node.js/npm or use --skip-frontend-build when frontend/dist is already built."
        )
    return executable


def _build_frontend(extension_dir: Path) -> None:
    package_json = extension_dir / "package.json"
    if not package_json.is_file():
        return

    npm = _resolve_executable("npm")
    install_command = "ci" if (extension_dir / "package-lock.json").is_file() else "install"
    _run([npm, install_command], extension_dir)
    _run([npm, "run", "build"], extension_dir)


def _copy_extension(extension_dir: Path, payload_dir: Path) -> None:
    def ignore(_directory: str, names: list[str]) -> set[str]:
        return {
            name
            for name in names
            if name in EXCLUDED_NAMES
            or name.endswith((".pyc", ".dvtx"))
        }

    shutil.copytree(extension_dir, payload_dir, ignore=ignore)


def _build_wheelhouse(payload_dir: Path, dependencies: list[str]) -> None:
    if not dependencies:
        return
    wheelhouse = payload_dir / ".dvt" / "wheels"
    wheelhouse.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "pip",
        "download",
        "--disable-pip-version-check",
        "--only-binary=:all:",
        "--dest",
        str(wheelhouse),
        "--implementation",
        "cp",
        "--python-version",
        "3.13",
        "--abi",
        "cp313",
        "--abi",
        "abi3",
        "--abi",
        "none",
        "--platform",
        "manylinux_2_28_x86_64",
        "--platform",
        "manylinux_2_17_x86_64",
        "--platform",
        "manylinux2014_x86_64",
        *dependencies,
    ]
    _run(command, payload_dir)


def _write_bundle_metadata(payload_dir: Path) -> None:
    metadata_dir = payload_dir / ".dvt"
    metadata_dir.mkdir(parents=True, exist_ok=True)
    (metadata_dir / "bundle.toml").write_text(
        "[bundle]\n"
        "schema_version = 1\n"
        'type = "dvt-extension"\n\n'
        "[runtime]\n"
        'os = "linux"\n'
        'arch = "x86_64"\n'
        'python = "3.13"\n',
        encoding="utf-8",
    )


def build_package(
    extension_dir: Path,
    *,
    output: Path | None,
    include_wheelhouse: bool,
    build_frontend: bool,
) -> Path:
    extension_dir = extension_dir.resolve()
    name, version, dependencies = _load_project(extension_dir)
    if build_frontend:
        _build_frontend(extension_dir)

    if output is None:
        output_path = extension_dir / "dist" / f"{name}-{version}.dvtx"
    else:
        resolved_output = output.resolve()
        output_path = (
            resolved_output
            if resolved_output.suffix.lower() == ".dvtx"
            else resolved_output / f"{name}-{version}.dvtx"
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="dvt-extension-package-") as tmp_dir:
        payload_dir = Path(tmp_dir) / f"{name}-{version}"
        _copy_extension(extension_dir, payload_dir)
        _write_bundle_metadata(payload_dir)
        if include_wheelhouse:
            _build_wheelhouse(payload_dir, dependencies)

        with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(payload_dir.rglob("*")):
                if path.is_dir():
                    continue
                archive.write(path, Path(payload_dir.name) / path.relative_to(payload_dir))

    return output_path


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output = build_package(
        args.extension_dir,
        output=args.output,
        include_wheelhouse=not args.skip_wheelhouse,
        build_frontend=not args.skip_frontend_build,
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
