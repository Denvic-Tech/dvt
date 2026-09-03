from __future__ import annotations

from pathlib import Path

import config

_DEFAULT_SOURCE_ROOTS = frozenset({"src", "services", "core", "scripts"})
_PROJECT_ROOT = config.PROJECT.ROOT_DIR.resolve()


def normalize_repo_relative_path(
    path_value: str | Path | None,
    *,
    allow_outside_root: bool = False,
) -> str | None:
    if not path_value:
        return None

    try:
        resolved = Path(path_value).resolve(strict=False)
    except Exception:
        return None

    try:
        relative = resolved.relative_to(_PROJECT_ROOT)
    except ValueError:
        return str(resolved) if allow_outside_root else None

    return relative.as_posix()


def repo_relative_path_to_module(
    relative_path: str,
    *,
    source_roots: set[str] | frozenset[str] = _DEFAULT_SOURCE_ROOTS,
) -> str | None:
    path = Path(relative_path)
    if path.suffix != ".py" or not path.parts or path.parts[0] not in source_roots:
        return None

    parts = list(path.parts)
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = path.stem

    return ".".join(parts) if parts else None
