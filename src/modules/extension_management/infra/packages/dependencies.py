from __future__ import annotations

import sys
from pathlib import Path

WHEELHOUSE_RELATIVE_PATH = Path(".dvt") / "wheels"


def get_extension_wheelhouse(install_root: Path) -> Path:
    return install_root / WHEELHOUSE_RELATIVE_PATH


def build_extension_pip_install_command(
    requirements: list[str],
    *,
    install_root: Path,
    offline_only: bool = False,
) -> list[str]:
    command = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check"]
    wheelhouse = get_extension_wheelhouse(install_root)

    if wheelhouse.is_dir():
        command.extend(["--no-index", "--find-links", str(wheelhouse)])
    elif offline_only:
        command.append("--no-index")

    command.extend(requirements)
    return command


__all__ = [
    "WHEELHOUSE_RELATIVE_PATH",
    "build_extension_pip_install_command",
    "get_extension_wheelhouse",
]
