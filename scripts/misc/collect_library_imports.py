"""Collect library imports from a Python file or directory."""

from __future__ import annotations

import argparse
import ast
import os
import sys
from importlib import metadata
from pathlib import Path

IGNORE_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    ".venv3.13",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "tmp",
    "venv",
    "venv3.13",
}

MODULE_ROOTS = ("src", "services", "core")


def _iter_python_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in IGNORE_DIRS]
        for filename in filenames:
            if filename.endswith(".py"):
                files.append(Path(dirpath) / filename)
    return files


def _build_module_map(project_root: Path) -> dict[str, set[Path]]:
    module_map: dict[str, set[Path]] = {}
    roots = [project_root]
    for name in MODULE_ROOTS:
        candidate = project_root / name
        if candidate.is_dir():
            roots.append(candidate)

    for root in roots:
        for file_path in _iter_python_files(root):
            try:
                relative = file_path.relative_to(root)
            except ValueError:
                continue
            if relative.name == "__init__.py":
                parts = relative.parts[:-1]
            else:
                parts = relative.with_suffix("").parts
            if not parts:
                continue
            module_name = ".".join(parts)
            module_map.setdefault(module_name, set()).add(file_path)
    return module_map


def _read_source(file_path: Path) -> str:
    with file_path.open("r", encoding="utf-8", errors="ignore") as handle:
        return handle.read()


def _resolve_module(module_map: dict[str, set[Path]], name: str) -> Path | None:
    candidates = module_map.get(name)
    if not candidates:
        return None
    return sorted(candidates, key=lambda path: str(path))[0]


def _resolve_relative_module(base_dir: Path, parts: list[str]) -> Path | None:
    base = base_dir.joinpath(*parts)
    candidates = (base.with_suffix(".py"), base / "__init__.py")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _handle_absolute_import(
    module_map: dict[str, set[Path]],
    name: str,
    queue: list[Path],
    libraries: set[str],
) -> None:
    resolved = _resolve_module(module_map, name)
    if resolved:
        queue.append(resolved)
        return
    libraries.add(name.split(".")[0])


def _handle_from_import(
    module_map: dict[str, set[Path]],
    module_name: str | None,
    names: list[ast.alias],
    queue: list[Path],
    libraries: set[str],
) -> None:
    if not module_name:
        return

    resolved = _resolve_module(module_map, module_name)
    if resolved:
        queue.append(resolved)
        return

    resolved_submodule = False
    for alias in names:
        candidate = f"{module_name}.{alias.name}"
        resolved_candidate = _resolve_module(module_map, candidate)
        if resolved_candidate:
            queue.append(resolved_candidate)
            resolved_submodule = True

    if not resolved_submodule:
        libraries.add(module_name.split(".")[0])


def _handle_relative_import(
    base_dir: Path,
    module_name: str | None,
    names: list[ast.alias],
    level: int,
    queue: list[Path],
) -> None:
    target_base = base_dir
    for _ in range(max(level - 1, 0)):
        target_base = target_base.parent

    if module_name:
        module_parts = module_name.split(".")
        resolved = _resolve_relative_module(target_base, module_parts)
        if resolved:
            queue.append(resolved)
        for alias in names:
            alias_parts = module_parts + [alias.name]
            resolved_alias = _resolve_relative_module(target_base, alias_parts)
            if resolved_alias:
                queue.append(resolved_alias)
        return

    for alias in names:
        resolved = _resolve_relative_module(target_base, [alias.name])
        if resolved:
            queue.append(resolved)


def _collect_from_file(
    file_path: Path,
    module_map: dict[str, set[Path]],
    queue: list[Path],
    libraries: set[str],
) -> None:
    try:
        tree = ast.parse(_read_source(file_path))
    except SyntaxError:
        return

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                _handle_absolute_import(module_map, alias.name, queue, libraries)
        elif isinstance(node, ast.ImportFrom):
            if node.level > 0:
                _handle_relative_import(
                    file_path.parent,
                    node.module,
                    node.names,
                    node.level,
                    queue,
                )
            else:
                _handle_from_import(
                    module_map,
                    node.module,
                    node.names,
                    queue,
                    libraries,
                )


def _collect_library_imports(input_path: Path) -> set[str]:
    project_root = Path(__file__).resolve().parents[1]
    module_map = _build_module_map(project_root)

    queue: list[Path] = []
    if input_path.is_dir():
        queue.extend(_iter_python_files(input_path))
    else:
        queue.append(input_path)

    visited: set[Path] = set()
    libraries: set[str] = set()

    while queue:
        file_path = queue.pop()
        if file_path in visited or not file_path.is_file():
            continue
        visited.add(file_path)
        _collect_from_file(file_path, module_map, queue, libraries)

    return libraries


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect library imports from Python sources.")
    parser.add_argument("path", help="Path to a directory or .py file")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    input_path = Path(args.path).resolve()
    if not input_path.exists():
        print(f"Path does not exist: {input_path}")
        return 2

    libraries = _collect_library_imports(input_path)
    stdlib = set(sys.stdlib_module_names)
    libraries = {name for name in libraries if name not in stdlib}
    for name in sorted(libraries):
        version = None
        try:
            version = metadata.version(name)
        except metadata.PackageNotFoundError:
            pass
        if version:
            print(f"{name}=={version}")
        else:
            print(name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
