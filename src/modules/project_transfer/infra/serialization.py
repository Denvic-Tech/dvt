"""Bundle <-> zip archive.

Layout::

    manifest.json
    connections.json
    secrets.enc                  (optional)
    projects/<project_ref>.json
    files/<project_ref>/<storage_path>
"""

from __future__ import annotations

import io
import posixpath
import tempfile
import zipfile
from typing import BinaryIO

from pydantic import ValidationError

from src.modules.project_transfer.domain.entities import ProjectBundle
from src.modules.project_transfer.domain.exceptions import (
    BundleTooLargeError,
    InvalidBundleError,
    UnsupportedBundleFormatError,
)
from src.modules.project_transfer.domain.types import BUNDLE_FORMAT_VERSION

from . import mappers
from .schemas import BundleManifestDoc, BundleProjectDoc, ConnectionsDoc

MANIFEST_PATH = "manifest.json"
CONNECTIONS_PATH = "connections.json"
SECRETS_PATH = "secrets.enc"
PROJECTS_DIR = "projects"
FILES_DIR = "files"
_SPOOL_MAX_SIZE = 64 * 1024 * 1024


def _project_doc_path(project_ref: str) -> str:
    return f"{PROJECTS_DIR}/{project_ref}.json"


def _file_entry_path(project_ref: str, storage_path: str) -> str:
    return f"{FILES_DIR}/{project_ref}/{storage_path.strip('/')}"


def _dump(model) -> bytes:
    return model.model_dump_json(indent=2, by_alias=True).encode("utf-8")


def write_bundle(bundle: ProjectBundle) -> BinaryIO:
    """Serialize a bundle to a seekable binary stream positioned at the start."""
    stream = tempfile.SpooledTemporaryFile(max_size=_SPOOL_MAX_SIZE)  # noqa: SIM115 - handed to the caller
    with zipfile.ZipFile(stream, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(MANIFEST_PATH, _dump(mappers.manifest_to_doc(bundle)))
        archive.writestr(
            CONNECTIONS_PATH,
            _dump(ConnectionsDoc(connections=[mappers.connection_to_doc(c) for c in bundle.connections])),
        )
        if bundle.encrypted_secrets:
            archive.writestr(SECRETS_PATH, bundle.encrypted_secrets)
        for project in bundle.projects:
            archive.writestr(_project_doc_path(project.ref), _dump(mappers.project_to_doc(project)))
            for file in project.files:
                if file.is_dir or file.content is None:
                    continue
                archive.writestr(_file_entry_path(project.ref, file.storage_path), file.content)
    stream.seek(0)
    return stream


def _validate_entry_name(name: str) -> None:
    normalized = posixpath.normpath(name)
    if name.startswith(("/", "\\")) or normalized.startswith("..") or "\\" in name or ":" in name:
        raise InvalidBundleError(f"Unsafe archive entry name: {name!r}")


def _load_json(archive: zipfile.ZipFile, path: str, model):
    try:
        raw = archive.read(path)
    except KeyError as exc:
        raise InvalidBundleError(f"Bundle is missing {path}") from exc
    try:
        return model.model_validate_json(raw)
    except ValidationError as exc:
        raise InvalidBundleError(f"{path} is malformed: {exc.errors()[0].get('msg', 'validation error')}") from exc


def read_bundle(
    data: bytes | BinaryIO,
    *,
    max_uncompressed_bytes: int,
    with_file_content: bool = True,
) -> ProjectBundle:
    """Parse an archive. Secrets stay encrypted; use the cipher to open them."""
    stream = io.BytesIO(data) if isinstance(data, (bytes, bytearray)) else data
    try:
        archive = zipfile.ZipFile(stream)
    except zipfile.BadZipFile as exc:
        raise InvalidBundleError("Bundle is not a valid zip archive") from exc

    with archive:
        total_uncompressed = 0
        for info in archive.infolist():
            _validate_entry_name(info.filename)
            total_uncompressed += info.file_size
            if total_uncompressed > max_uncompressed_bytes:
                raise BundleTooLargeError(
                    f"Bundle uncompressed size exceeds {max_uncompressed_bytes} bytes"
                )

        manifest_doc = _load_json(archive, MANIFEST_PATH, BundleManifestDoc)
        if manifest_doc.format_version != BUNDLE_FORMAT_VERSION:
            raise UnsupportedBundleFormatError(
                f"Bundle format version {manifest_doc.format_version} is not supported "
                f"(expected {BUNDLE_FORMAT_VERSION})"
            )

        connections_doc = (
            _load_json(archive, CONNECTIONS_PATH, ConnectionsDoc)
            if CONNECTIONS_PATH in archive.namelist()
            else ConnectionsDoc()
        )
        encrypted_secrets = archive.read(SECRETS_PATH) if SECRETS_PATH in archive.namelist() else None

        projects = []
        for entry in manifest_doc.projects:
            project_doc = _load_json(archive, _project_doc_path(entry.ref), BundleProjectDoc)
            project = mappers.project_from_doc(project_doc)
            if with_file_content:
                for file in project.files:
                    if file.is_dir:
                        continue
                    entry_path = _file_entry_path(project.ref, file.storage_path)
                    try:
                        file.content = archive.read(entry_path)
                    except KeyError as exc:
                        raise InvalidBundleError(f"Bundle is missing file entry {entry_path}") from exc
                    file.size = len(file.content)
            projects.append(project)

    return ProjectBundle(
        manifest=mappers.manifest_from_doc(manifest_doc),
        folders=[mappers.folder_from_doc(folder) for folder in manifest_doc.folders],
        projects=projects,
        connections=[mappers.connection_from_doc(c) for c in connections_doc.connections],
        encrypted_secrets=encrypted_secrets,
    )
