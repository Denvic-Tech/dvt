"""Write a private, portable recovery point and verify the stored bytes."""

from __future__ import annotations

import gzip
import hashlib
import os
import shutil
import stat
import tarfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from uuid import UUID

from ..domain.release_manifest import canonical_json, strict_json
from .maintenance_host import ComposeMaintenanceHost, MaintenancePrerequisite
from .operation_files import (
    _require_private,
    _require_regular_file,
    prepare_directory,
    sync_directory,
)
from .staging_artifacts import read_artifact, write_artifact

FILES = ("database.dump", "globals.sql", "data.tar.gz")
COMPLETE_GLOBALS = b"-- PostgreSQL database cluster dump complete"
REQUIRED_FILES = {
    ".env", "docker-compose.yaml", ".bootstrap/host.json",
    ".installation-state/journal.sqlite3",
}
INTERNAL_EXCLUSIONS = {
    ".bootstrap/pairing.json",
    ".bootstrap/launch.lock",
    ".bootstrap/pairing.lock",
    ".installation-state/executor.lock",
}


def backup_exclusions(data: Path, backup: Path, temporary: Path, pgdata: Path) -> set[str]:
    if (
        any(path == data or data.is_relative_to(path) for path in (backup, temporary, pgdata))
        or any(
            path.is_relative_to(pgdata) or pgdata.is_relative_to(path)
            for path in (backup, temporary)
        )
    ):
        raise MaintenancePrerequisite("The data, PostgreSQL and backup paths overlap")
    return INTERNAL_EXCLUSIONS | {
        path.relative_to(data).as_posix()
        for path in (backup, temporary, pgdata)
        if path.is_relative_to(data)
    }


def _members(directory: Path, exclusions: set[str]):
    def walk(parent: Path):
        for path in sorted(parent.iterdir()):
            name = path.relative_to(directory).as_posix()
            if name in exclusions:
                continue
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode):
                target = path.resolve(strict=True)
                if (
                    not target.is_relative_to(directory)
                    or path.readlink().is_absolute()
                    or any(
                        target.is_relative_to(directory / item) for item in exclusions
                    )
                ):
                    raise MaintenancePrerequisite(
                        "A persistent symlink refers outside the portable copy"
                    )
            elif not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
                raise MaintenancePrerequisite("A persistent path has an unsupported file type")
            yield path, name, info
            if stat.S_ISDIR(info.st_mode):
                yield from walk(path)

    yield from walk(directory)


def _inventory(data: Path, exclusions: set[str]) -> int:
    files: set[str] = set()
    total = 0
    for _, name, info in _members(data, exclusions):
        if stat.S_ISREG(info.st_mode):
            files.add(name)
            total += info.st_size
    if not files >= REQUIRED_FILES:
        raise MaintenancePrerequisite("DVT identity, environment or Compose configuration is missing")
    return total


def preflight(data: Path, backup: Path, temporary: Path, pgdata: Path) -> dict:
    exclusions = backup_exclusions(data, backup, temporary, pgdata)
    prepare_directory(backup)
    space = shutil.disk_usage(backup)
    # A conservative reserve: full uncompressed persistent files plus a physical PG estimate.
    # The dumps can still outgrow it; partial files never become a verified backup.
    data_size = _inventory(data, exclusions)
    pg_size = sum(
        info.st_size for _, _, info in _members(pgdata, set()) if stat.S_ISREG(info.st_mode)
    )
    if space.free < data_size + pg_size + 32 * 1024**2 or os.statvfs(backup).f_favail < 16:
        raise MaintenancePrerequisite("The selected backup filesystem has insufficient space")
    return {
        "postgres_data": pgdata.relative_to(data).as_posix(),
        "separate_filesystem": (
            backup.stat().st_dev not in {data.stat().st_dev, pgdata.stat().st_dev}
        ),
        "excluded_paths": sorted(exclusions),
    }


def _fingerprint(path: Path) -> dict:
    info = path.lstat()
    _require_regular_file(info)
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if not info.st_size:
        raise ValueError("A recovery artifact is empty")
    return {"bytes": info.st_size, "digest": f"sha256:{digest}"}


def _archive(path: Path, data: Path, excluded: set[str]) -> None:
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as stream:
        with tarfile.open(fileobj=stream, mode="w:gz", dereference=False) as archive:
            for source, name, _ in _members(data, excluded):
                archive.add(source, arcname=name, recursive=False)
        stream.flush()
        os.fsync(stream.fileno())


def _verify_archive(path: Path) -> None:
    regular_files: set[str] = set()
    seen: set[str] = set()
    # The gzip stream is consumed to EOF to check its CRC as well as each tar member.
    with gzip.open(path, "rb") as compressed, tarfile.open(fileobj=compressed, mode="r|") as tar:
        for item in tar:
            name = PurePosixPath(item.name)
            if name.is_absolute() or ".." in name.parts or str(name) in seen:
                raise ValueError("Invalid path in DVT archive")
            if item.isfile():
                payload = tar.extractfile(item)
                if payload is None:
                    raise ValueError("Missing data in DVT archive")
                with payload:
                    while payload.read(1024 * 1024):
                        pass
                regular_files.add(str(name))
            elif item.islnk():
                if item.linkname not in regular_files:
                    raise ValueError("Invalid hard link in DVT archive")
                regular_files.add(str(name))
            elif item.issym():
                target = PurePosixPath(item.linkname)
                depth = len(name.parent.parts)
                for part in target.parts:
                    depth += -1 if part == ".." else 1
                    if depth < 0:
                        raise ValueError("Symlink leaves DVT archive")
                if target.is_absolute():
                    raise ValueError("Absolute symlink in DVT archive")
            elif not item.isdir():
                raise ValueError("Unexpected type in DVT archive")
            seen.add(str(name))
        while compressed.read(1024 * 1024):
            pass
    if not regular_files >= REQUIRED_FILES:
        raise ValueError("The DVT archive is missing configuration or identity")


def read_copy_manifest(directory: Path) -> tuple[bytes, dict]:
    info = directory.lstat()
    _require_private(info, 0o700)
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError("The backup directory is not a directory")
    content = read_artifact(directory / "manifest.json", 256 * 1024)
    if content is None:
        raise ValueError("The backup manifest is missing")
    manifest = strict_json(content)
    if not isinstance(manifest, dict) or datetime.fromisoformat(manifest["created_at"]).tzinfo != UTC:
        raise ValueError("Invalid recovery point date")
    return content, manifest


def verify_copy_files(directory: Path, manifest: dict) -> None:
    if manifest["artifacts"] != {name: _fingerprint(directory / name) for name in FILES}:
        raise ValueError("The recovery point does not match the committed digests")
    with (directory / "globals.sql").open("rb") as stream:
        header = stream.read(512)
        stream.seek(max(0, (directory / "globals.sql").stat().st_size - 512))
        if b"-- PostgreSQL database cluster dump" not in header or COMPLETE_GLOBALS not in stream.read():
            raise ValueError("The PostgreSQL globals dump is incomplete")
    _verify_archive(directory / "data.tar.gz")


def verify_copy(
    directory: Path, metadata: dict, host: ComposeMaintenanceHost, pg_container: str
) -> None:
    _, manifest = read_copy_manifest(directory)
    if {key: value for key, value in manifest.items()
        if key not in {"created_at", "artifacts"}} != metadata:
        raise ValueError("The recovery point does not match the committed metadata")
    verify_copy_files(directory, manifest)
    with (directory / "database.dump").open("rb") as stream:
        host.postgres_tool(pg_container, "database.dump", stream, verify=True)


def create_copy(
    backup: Path, operation_id: UUID, metadata: dict, host: ComposeMaintenanceHost,
    pg_container: str, *, confirm_source_sealed: Callable[[], object],
) -> None:
    final = backup / str(operation_id)
    if final.exists() or final.is_symlink():
        verify_copy(final, metadata, host, pg_container)
        confirm_source_sealed()
        return
    with TemporaryDirectory(dir=backup, prefix=f".partial-{operation_id}-") as folder:
        directory = Path(folder)
        for name in ("database.dump", "globals.sql"):
            with os.fdopen(os.open(directory / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as stream:
                host.postgres_tool(pg_container, name, stream)
                stream.flush()
                os.fsync(stream.fileno())
        _archive(directory / "data.tar.gz", host.data, set(metadata["layout"]["excluded_paths"]))
        write_artifact(
            directory / "manifest.json",
            canonical_json({
                **metadata,
                "created_at": datetime.now(UTC).isoformat(),
                "artifacts": {name: _fingerprint(directory / name) for name in FILES},
            }),
        )
        verify_copy(directory, metadata, host, pg_container)
        confirm_source_sealed()
        directory.rename(final)
        sync_directory(backup)
