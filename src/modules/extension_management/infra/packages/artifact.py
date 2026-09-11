from __future__ import annotations

import re
import shutil
import stat
import time
import tomllib
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO
from uuid import UUID, uuid4

from packaging.version import InvalidVersion, Version

from src.modules.extension_management.domain.value_objects import ExtensionManifest
from src.modules.extension_management.infra.packages.dependencies import get_extension_wheelhouse
from src.modules.extension_management.infra.runtime.loader import load_manifest_payload

import config

_PACKAGE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_ALLOWED_SUFFIXES = {".dvtx", ".zip"}


@dataclass(frozen=True)
class StagedExtensionPackage:
    package_id: str
    original_filename: str
    stage_dir: Path
    archive_path: Path
    root_dir: Path
    manifest: ExtensionManifest
    bundled_wheels_count: int

    @property
    def has_wheelhouse(self) -> bool:
        return get_extension_wheelhouse(self.root_dir).is_dir()


def _staging_root() -> Path:
    return Path(config.EXTENSIONS.EXTENSIONS_DATA_DIR).resolve() / ".staging"


def cleanup_staged_packages() -> None:
    root = _staging_root()
    if not root.is_dir():
        return
    cutoff = time.time() - config.EXTENSIONS.PACKAGE_STAGE_TTL_SEC
    for child in root.iterdir():
        try:
            if child.is_dir() and child.stat().st_mtime < cutoff:
                shutil.rmtree(child, ignore_errors=True)
        except OSError:
            continue


def _validate_package_id(package_id: str) -> str:
    try:
        return str(UUID(package_id))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError("Invalid extension package id") from exc


def _normalized_member_path(filename: str) -> PurePosixPath:
    normalized = filename.replace("\\", "/")
    path = PurePosixPath(normalized)
    if not normalized or normalized.startswith("/") or path.is_absolute():
        raise ValueError(f"Unsafe archive path: {filename}")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"Unsafe archive path: {filename}")
    return path


def _validate_archive_members(archive: zipfile.ZipFile) -> None:
    infos = archive.infolist()
    if len(infos) > config.EXTENSIONS.PACKAGE_MAX_FILES:
        raise ValueError("Extension package contains too many files")

    seen: set[str] = set()
    total_uncompressed = 0
    total_compressed = 0
    for member in infos:
        path = _normalized_member_path(member.filename)
        normalized = path.as_posix().rstrip("/")
        if normalized in seen:
            raise ValueError(f"Duplicate archive entry: {member.filename}")
        seen.add(normalized)

        if member.flag_bits & 0x1:
            raise ValueError("Encrypted extension packages are not supported")

        mode = member.external_attr >> 16
        if mode and stat.S_ISLNK(mode):
            raise ValueError(f"Symlinks are not allowed in extension packages: {member.filename}")
        if mode and not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
            file_type = stat.S_IFMT(mode)
            if file_type:
                raise ValueError(f"Special files are not allowed in extension packages: {member.filename}")

        total_uncompressed += member.file_size
        total_compressed += member.compress_size
        if total_uncompressed > config.EXTENSIONS.PACKAGE_MAX_UNCOMPRESSED_SIZE_BYTES:
            raise ValueError("Extension package is too large after extraction")

    if total_uncompressed and total_compressed:
        ratio = total_uncompressed / max(total_compressed, 1)
        if ratio > config.EXTENSIONS.PACKAGE_MAX_COMPRESSION_RATIO:
            raise ValueError("Extension package compression ratio is suspiciously high")


def _extract_package(archive_path: Path, target_dir: Path) -> Path:
    if not zipfile.is_zipfile(archive_path):
        raise ValueError("Extension package is not a valid ZIP archive")

    target_dir.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(archive_path) as archive:
        _validate_archive_members(archive)
        target_root = target_dir.resolve()
        for member in archive.infolist():
            relative = Path(*_normalized_member_path(member.filename).parts)
            destination = (target_root / relative).resolve()
            try:
                destination.relative_to(target_root)
            except ValueError as exc:
                raise ValueError(f"Unsafe archive path: {member.filename}") from exc
            archive.extract(member, target_root)

    items = list(target_dir.iterdir())
    root_dir = items[0] if len(items) == 1 and items[0].is_dir() else target_dir
    return root_dir.resolve()


def _validate_bundle_metadata(root_dir: Path, *, required: bool) -> None:
    metadata_path = root_dir / ".dvt" / "bundle.toml"
    if not metadata_path.is_file():
        if required:
            raise ValueError(".dvtx package must contain .dvt/bundle.toml")
        return

    try:
        payload = tomllib.loads(metadata_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ValueError("Invalid .dvt/bundle.toml") from exc
    bundle = payload.get("bundle") or {}
    runtime = payload.get("runtime") or {}
    if bundle.get("schema_version") != 1 or bundle.get("type") != "dvt-extension":
        raise ValueError("Unsupported DVT extension bundle format")
    expected = {"os": "linux", "arch": "x86_64", "python": "3.13"}
    mismatches = [
        f"{key}={runtime.get(key)!r}"
        for key, value in expected.items()
        if runtime.get(key) != value
    ]
    if mismatches:
        raise ValueError(
            "Unsupported extension runtime target: " + ", ".join(mismatches)
        )


def _validate_manifest(root_dir: Path) -> ExtensionManifest:
    manifest = load_manifest_payload(root_dir)
    if manifest is None:
        raise ValueError(f"Extension package must contain '{config.EXTENSIONS.MANIFEST_FILE}'")
    if not manifest.name or not _PACKAGE_NAME_RE.fullmatch(manifest.name):
        raise ValueError(f"Invalid extension name in manifest: '{manifest.name}'")
    if not manifest.version:
        raise ValueError("Extension version is required in manifest")
    try:
        Version(manifest.version)
    except InvalidVersion as exc:
        raise ValueError(f"Invalid extension version: '{manifest.version}'") from exc
    return manifest


def stage_extension_package(fileobj: BinaryIO, filename: str | None) -> StagedExtensionPackage:
    cleanup_staged_packages()
    safe_filename = Path(filename or "extension.dvtx").name
    suffix = Path(safe_filename).suffix.lower()
    if suffix not in _ALLOWED_SUFFIXES:
        raise ValueError("Only .dvtx and .zip extension packages are supported")

    package_id = str(uuid4())
    stage_dir = _staging_root() / package_id
    stage_dir.mkdir(parents=True, exist_ok=False)
    archive_path = stage_dir / f"package{suffix}"

    try:
        fileobj.seek(0)
        total = 0
        with archive_path.open("wb") as output:
            while chunk := fileobj.read(1024 * 1024):
                total += len(chunk)
                if total > config.EXTENSIONS.PACKAGE_MAX_SIZE_BYTES:
                    raise ValueError("Extension package is too large")
                output.write(chunk)
        if total == 0:
            raise ValueError("Extension package is empty")

        root_dir = _extract_package(archive_path, stage_dir / "payload")
        _validate_bundle_metadata(root_dir, required=suffix == ".dvtx")
        manifest = _validate_manifest(root_dir)
        wheelhouse = get_extension_wheelhouse(root_dir)
        wheel_count = len(list(wheelhouse.glob("*.whl"))) if wheelhouse.is_dir() else 0
        return StagedExtensionPackage(
            package_id=package_id,
            original_filename=safe_filename,
            stage_dir=stage_dir,
            archive_path=archive_path,
            root_dir=root_dir,
            manifest=manifest,
            bundled_wheels_count=wheel_count,
        )
    except Exception:
        shutil.rmtree(stage_dir, ignore_errors=True)
        raise


def get_staged_extension_package(package_id: str) -> StagedExtensionPackage:
    normalized_id = _validate_package_id(package_id)
    stage_dir = _staging_root() / normalized_id
    if not stage_dir.is_dir():
        raise FileNotFoundError("Extension package was not found or has expired")

    archive_candidates = [
        path for path in stage_dir.iterdir() if path.is_file() and path.suffix.lower() in _ALLOWED_SUFFIXES
    ]
    if len(archive_candidates) != 1:
        raise ValueError("Staged extension package is corrupted")
    archive_path = archive_candidates[0]
    payload_dir = stage_dir / "payload"
    if not payload_dir.is_dir():
        raise ValueError("Staged extension package payload is missing")
    items = list(payload_dir.iterdir())
    root_dir = items[0] if len(items) == 1 and items[0].is_dir() else payload_dir
    root_dir = root_dir.resolve()
    _validate_bundle_metadata(root_dir, required=archive_path.suffix.lower() == ".dvtx")
    manifest = _validate_manifest(root_dir)
    wheelhouse = get_extension_wheelhouse(root_dir)
    wheel_count = len(list(wheelhouse.glob("*.whl"))) if wheelhouse.is_dir() else 0
    return StagedExtensionPackage(
        package_id=normalized_id,
        original_filename=archive_path.name,
        stage_dir=stage_dir,
        archive_path=archive_path,
        root_dir=root_dir,
        manifest=manifest,
        bundled_wheels_count=wheel_count,
    )


def discard_staged_extension_package(package_id: str) -> None:
    normalized_id = _validate_package_id(package_id)
    shutil.rmtree(_staging_root() / normalized_id, ignore_errors=True)


__all__ = [
    "StagedExtensionPackage",
    "cleanup_staged_packages",
    "discard_staged_extension_package",
    "get_staged_extension_package",
    "stage_extension_package",
]
