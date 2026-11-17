from __future__ import annotations

import os
import sys
from email.parser import BytesParser
from pathlib import Path
from zipfile import ZipFile

from packaging.requirements import Requirement

WHEELHOUSE_RELATIVE_PATH = Path(".dvt") / "wheels"
OFFLINE_EXTENSION_ENV = "DVT_EXTENSION_OFFLINE_ONLY"


def get_extension_wheelhouse(install_root: Path) -> Path:
    return install_root / WHEELHOUSE_RELATIVE_PATH


def extension_pip_environment() -> dict[str, str] | None:
    if os.environ.get(OFFLINE_EXTENSION_ENV) != "true":
        return None
    # PIP_FIND_LINKS, PIP_REQUIREMENT and PIP_CONSTRAINT can otherwise bypass
    # source isolation even when the command includes --no-index.
    return {key: value for key, value in os.environ.items() if not key.startswith("PIP_")} | {
        "PIP_CONFIG_FILE": os.devnull,
    }


def _verify_local_requirements(requirements: list[str], wheelhouse: Path) -> None:
    def named(requirement: str) -> None:
        if Requirement(requirement).url is not None:
            raise ValueError("Offline extensions require named wheel dependencies")

    for requirement in requirements:
        named(requirement)
    for wheel in wheelhouse.iterdir() if wheelhouse.is_dir() else ():
        if not wheel.is_file() or wheel.is_symlink() or wheel.suffix != ".whl":
            raise ValueError("The offline wheelhouse must contain local wheels")
        with ZipFile(wheel) as archive:
            (entry,) = [
                item for item in archive.infolist()
                if item.filename.endswith(".dist-info/METADATA")
            ]
            if entry.file_size > 1024 * 1024:
                raise ValueError("Wheel metadata exceeds the offline limit")
            metadata = BytesParser().parsebytes(archive.read(entry))
        for requirement in metadata.get_all("Requires-Dist", []):
            named(requirement)


def build_extension_pip_install_command(
    requirements: list[str],
    *,
    install_root: Path,
    offline_only: bool = False,
) -> list[str]:
    command = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check"]
    wheelhouse = get_extension_wheelhouse(install_root)

    if os.environ.get(OFFLINE_EXTENSION_ENV) == "true":
        _verify_local_requirements(requirements, wheelhouse)
        command.extend(["--no-index", "--only-binary=:all:", "--no-cache-dir"])
        if wheelhouse.is_dir():
            command.extend(["--find-links", str(wheelhouse)])
    elif wheelhouse.is_dir():
        command.extend(["--no-index", "--find-links", str(wheelhouse)])
    elif offline_only:
        command.append("--no-index")

    command.extend(requirements)
    return command


__all__ = [
    "WHEELHOUSE_RELATIVE_PATH",
    "build_extension_pip_install_command",
    "extension_pip_environment",
    "get_extension_wheelhouse",
]
