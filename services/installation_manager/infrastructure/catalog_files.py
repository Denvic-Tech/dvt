"""Owner-only, atomic catalog snapshots and digest-addressed verified bytes."""

from __future__ import annotations

import stat
from pathlib import Path

from ..domain.operation_state import ReleasePin
from ..host_bootstrap import CONTROL, atomic_write
from .operation_files import _require_private, prepare_directory
from .release_verification import MAX_MANIFEST_BYTES
from .staging_artifacts import read_artifact, write_artifact


def _directory(data: Path, *, create: bool = False) -> Path | None:
    parent = data / CONTROL
    directory = parent / "release-catalog"
    for path in (parent, directory):
        try:
            info = path.lstat()
        except FileNotFoundError:
            if not create:
                return None
            prepare_directory(path)
            continue
        if not stat.S_ISDIR(info.st_mode):
            raise PermissionError("Catalog state must be a real directory")
        _require_private(info, 0o700)
    return directory


def read_catalog(data: Path, limit: int) -> bytes | None:
    directory = _directory(data)
    return read_artifact(directory / "catalog.json", limit) if directory is not None else None


def write_catalog(data: Path, content: bytes) -> None:
    directory = _directory(data, create=True)
    atomic_write(directory / "catalog.json", content)


def read_selected_manifest(data: Path, pin: ReleasePin) -> bytes | None:
    directory = _directory(data)
    if directory is None:
        return None
    return read_artifact(directory / f"{pin.manifest_digest[7:]}.json", MAX_MANIFEST_BYTES)


def write_selected_manifest(data: Path, pin: ReleasePin, content: bytes) -> None:
    directory = _directory(data, create=True)
    write_artifact(directory / f"{pin.manifest_digest[7:]}.json", content)
