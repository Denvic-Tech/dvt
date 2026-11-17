"""Verify and extract the signed DVT offline transport before Docker can consume it."""

from __future__ import annotations

import gzip
import hashlib
import os
import re
import shutil
import stat
import tarfile
import zlib
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import BinaryIO
from uuid import NAMESPACE_URL, UUID, uuid5

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from ..domain.operation_state import FailureReason, ReleasePin
from ..domain.release_manifest import (
    ReleaseManifest,
    SignedRelease,
    StagingError,
    canonical_json,
    digest_of,
    strict_json,
)
from .operation_files import sync_directory
from .release_verification import MAX_MANIFEST_BYTES, TrustPolicy, invalid_package, verify_file

OFFLINE_CONTEXT = b"DVT offline bundle v1\0"
MAX_INDEX = 1024 * 1024
MAX_FILES = 4096
MAX_FILE = 8 * 1024**3 - 1  # USTAR size field
MAX_TOTAL = 64 * 1024**3
BLOCK = 512
CHUNK = 1024 * 1024
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
COMPONENT = re.compile(r"[A-Za-z0-9_.+~-]{1,160}")
PLATFORMS = {"debian": "13", "ubuntu": "24.04"}
LOCAL_DOCKER_PACKAGES = frozenset({
    "containerd.io", "docker-ce", "docker-ce-cli", "docker-buildx-plugin", "docker-compose-plugin",
})
MANIFEST_TYPES = {
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
}
CONFIG_TYPES = {
    "application/vnd.oci.image.config.v1+json",
    "application/vnd.docker.container.image.v1+json",
}
LAYER_TYPES = {
    "application/vnd.oci.image.layer.v1.tar",
    "application/vnd.oci.image.layer.v1.tar+gzip",
    "application/vnd.oci.image.layer.v1.tar+zstd",
    "application/vnd.docker.image.rootfs.diff.tar.gzip",
}


def _reject() -> StagingError:
    return invalid_package("The offline bundle is malformed, incomplete or has changed")


def _valid_path(name: str) -> bool:
    parts = name.split("/")
    return (
        len(name) <= 250 and len(parts) <= 16 and len(parts[-1]) <= 100
        and all(part not in {".", ".."} and COMPONENT.fullmatch(part) for part in parts)
    )


def _inventory_directories(files: dict) -> set[str]:
    return {
        parent.as_posix() for name in files for parent in PurePosixPath(name).parents
        if parent.parts
    }


@dataclass(frozen=True)
class Member:
    name: str
    size: int


class TarReader:
    """Only ordinary USTAR headers are processed. No PAX/GNU metadata is expanded."""

    def __init__(self, stream: BinaryIO, *, directories: frozenset[str] = frozenset()) -> None:
        self.stream = stream
        self.directories = directories

    def _read(self, length: int) -> bytes:
        content = self.stream.read(length)
        if len(content) != length:
            raise _reject()
        return content

    def members(self) -> Iterator[Member]:
        seen: set[str] = set()
        total = 0
        while True:
            header = self._read(BLOCK)
            if header == bytes(BLOCK):
                # Allow ordinary tar record padding and validate the gzip footer.
                if self._read(BLOCK) != bytes(BLOCK):
                    raise _reject()
                tail = self.stream.read(20 * BLOCK + 1)
                if len(tail) > 20 * BLOCK or any(tail) or len(tail) % BLOCK:
                    raise _reject()
                return
            if header[257:265] != b"ustar\x0000" or header[156:157] not in {b"0", b"\x00", b"5"}:
                raise _reject()
            info = tarfile.TarInfo.frombuf(header, "ascii", "strict")
            name = info.name.rstrip("/") if info.isdir() else info.name
            if (
                not _valid_path(name) or name in seen or len(seen) >= MAX_FILES
                or not 0 <= info.size <= MAX_FILE or info.linkname or info.issparse()
            ):
                raise _reject()
            total += info.size
            if total > MAX_TOTAL:
                raise _reject()
            seen.add(name)
            if info.isdir():
                if name not in self.directories or info.size:
                    raise _reject()
                continue
            yield Member(name, info.size)
            padding = self._read(-info.size % BLOCK)
            if any(padding):
                raise _reject()

    def small(self, member: Member, expected_name: str, limit: int) -> bytes:
        if member.name != expected_name or not 0 < member.size <= limit:
            raise _reject()
        return self._read(member.size)

    def copy(self, member: Member, output: BinaryIO | None = None) -> str:
        sha = hashlib.sha256()
        remaining = member.size
        while remaining:
            chunk = self._read(min(remaining, CHUNK))
            sha.update(chunk)
            if output is not None:
                output.write(chunk)
            remaining -= len(chunk)
        return "sha256:" + sha.hexdigest()


@dataclass(frozen=True)
class OfflineBundle:
    directory: Path
    index: dict
    signed: bytes
    pin: ReleasePin
    release: ReleaseManifest

    @property
    def id(self) -> UUID:
        return uuid5(NAMESPACE_URL, "urn:dvt:offline:" + digest_of(canonical_json(self.index)))

    @property
    def images(self) -> dict[str, str]:
        return self.index["images"]

    @property
    def extensions(self) -> tuple[str, ...]:
        return tuple(self.index["extensions"])

    def verify_asset(self, name: str) -> bytes:
        descriptor = self.index["files"][name]
        with (self.directory / name).open("rb") as stream:
            content = stream.read(descriptor["size"] + 1)
        if len(content) != descriptor["size"] or digest_of(content) != descriptor["digest"]:
            raise _reject()
        return content


def verify_index(
    directory: Path, raw: bytes, signature: bytes, signed: bytes, trust: TrustPolicy,
    *, now: datetime | None = None,
) -> OfflineBundle:
    try:
        index = strict_json(raw)
        if (
            not isinstance(index, dict)
            or set(index) != {
                "format_version", "root_id", "release_id", "manifest_digest", "kind",
                "platform", "distribution", "distribution_version", "profiles",
                "images", "extensions", "files",
            }
            or raw != canonical_json(index)
            or type(index["format_version"]) is not int or index["format_version"] != 1
            or index["kind"] not in {"install", "update"}
            or index["platform"] != "linux/amd64"
            or PLATFORMS[index["distribution"]] != index["distribution_version"]
            or index["profiles"] not in ([], ["ai-mcp"])
            or not re.fullmatch(rb"[0-9a-f]{128}", signature)
        ):
            raise _reject()
        pin = ReleasePin(index["release_id"], index["manifest_digest"])
        release = trust.verify(signed, pin, now=now)
        cert = SignedRelease.model_validate(strict_json(signed)).signing_key
        if index["root_id"] != cert.root_id:
            raise _reject()
        signer = Ed25519PublicKey.from_public_bytes(bytes.fromhex(cert.public_key))
        signer.verify(bytes.fromhex(signature.decode("ascii")), OFFLINE_CONTEXT + raw)
        distribution = release.platforms[index["platform"]]
        if (
            index["distribution_version"] not in release.environment.distributions.get(
                index["distribution"], []
            )
            or not set(index["profiles"]) <= release.environment.profiles.keys()
            or (index["kind"] == "install" and not release.database_schema.initial_install)
            or (index["kind"] == "update" and not release.database_schema.from_releases)
        ):
            raise _reject()
        refs = {image.reference for image in distribution.images.values()}
        images = {
            ref: f"images/{hashlib.sha256(ref.encode('ascii')).hexdigest()}.tar"
            for ref in refs
        }
        names = index["extensions"]
        if (
            images != index["images"] or not isinstance(names, list)
            or len(names) > 128 or any(not NAME.fullmatch(name) for name in names)
            or names != sorted(set(names))
            or not set(release.database_schema.required_extensions) <= set(names)
        ):
            raise _reject()
        files = index["files"]
        expected = {"compose.yaml", "bootstrap.sh", "install.sh", "update.sh", *images.values()}
        if not isinstance(files, dict) or not expected <= files.keys() or len(files) > MAX_FILES - 3:
            raise _reject()
        ext_files = {name: set() for name in names}
        debs = []
        for name, item in files.items():
            if (
                not _valid_path(name) or not isinstance(item, dict)
                or set(item) != {"size", "digest"} or type(item["size"]) is not int
                or not 0 <= item["size"] <= MAX_FILE or not DIGEST.fullmatch(item["digest"])
                or (item["size"] == 0 and not name.startswith("extensions/"))
            ):
                raise _reject()
            if name in expected:
                continue
            if re.fullmatch(r"docker/[A-Za-z0-9_.+~-]+\.deb", name):
                debs.append(name)
            elif len(parts := name.split("/", 2)) == 3 and parts[0] == "extensions" and parts[1] in ext_files:
                ext_files[parts[1]].add(parts[2])
            else:
                raise _reject()
        directories = _inventory_directories(files)
        if (
            len(directories) > MAX_FILES or directories.intersection(files)
            or (index["kind"] == "install") != bool(debs)
            or any("pyproject.toml" not in paths for paths in ext_files.values())
            or sum(item["size"] for item in files.values()) > MAX_TOTAL
        ):
            raise _reject()
        for name, descriptor in (
            ("compose.yaml", distribution.compose), ("bootstrap.sh", distribution.bootstrap)
        ):
            if files[name] != {"size": descriptor.size, "digest": descriptor.digest}:
                raise _reject()
        return OfflineBundle(directory, index, signed, pin, release)
    except (InvalidSignature, KeyError, TypeError, ValueError, UnicodeError, RecursionError):
        raise _reject() from None


def extract_bundle(source: Path, directory: Path, trust: TrustPolicy) -> OfflineBundle:
    """Write to a caller-owned private temporary directory and verify the entire stream."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        with os.fdopen(os.open(source, flags), "rb") as raw:
            status = os.fstat(raw.fileno())
            if not stat.S_ISREG(status.st_mode) or status.st_size > MAX_TOTAL:
                raise _reject()
            with gzip.GzipFile(fileobj=raw) as stream:
                reader = TarReader(stream)
                members = reader.members()
                index = reader.small(next(members), "bundle.json", MAX_INDEX)
                signature = reader.small(next(members), "bundle.sig", 128)
                signed = reader.small(next(members), "manifest.json", MAX_MANIFEST_BYTES)
                bundle = verify_index(directory, index, signature, signed, trust)
                expected = bundle.index["files"]
                if (
                    sum(item["size"] for item in expected.values()) + 16 * 1024**2
                    > shutil.disk_usage(directory).free
                    or (
                        hasattr(os, "statvfs")
                        and len(expected) + len(_inventory_directories(expected)) + 16
                        > os.statvfs(directory).f_favail
                    )
                ):
                    raise StagingError(
                        FailureReason.DISK_SPACE,
                        "The staging filesystem cannot contain the offline bundle",
                        "Free space and inodes and retry the same archive",
                        retryable=True,
                    )
                seen = set()
                directories = {directory}
                for member in members:
                    item = expected.get(member.name)
                    if item is None or item["size"] != member.size:
                        raise _reject()
                    path = directory / member.name
                    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                    directories.update(parent for parent in path.parents if parent.is_relative_to(directory))
                    with path.open("xb") as output:
                        if reader.copy(member, output) != item["digest"]:
                            raise _reject()
                        output.flush()
                        os.fsync(output.fileno())
                    path.chmod(0o600)
                    seen.add(member.name)
                if seen != set(expected):
                    raise _reject()
                for name, content in (
                    ("bundle.json", index), ("bundle.sig", signature), ("manifest.json", signed),
                ):
                    path = directory / name
                    with path.open("xb") as output:
                        output.write(content)
                        output.flush()
                        os.fsync(output.fileno())
                    path.chmod(0o600)
                for folder in sorted(directories, key=lambda path: len(path.parts), reverse=True):
                    sync_directory(folder)
                platform = bundle.release.platforms[bundle.index["platform"]]
                verify_file(bundle.verify_asset("compose.yaml"), platform.compose, "compose.yaml")
                verify_file(bundle.verify_asset("bootstrap.sh"), platform.bootstrap, "bootstrap.sh")
                return bundle
    except (EOFError, gzip.BadGzipFile, tarfile.HeaderError, StopIteration, UnicodeError, zlib.error):
        raise _reject() from None


def image_alias(reference: str) -> str:
    repository, digest = reference.split("@sha256:")
    return f"{repository}:dvt-offline-{digest}"


def inspect_oci(path: Path, reference: str, platform: str) -> tuple[str, list[str]]:
    """Check the one leaf, manifest, config and every layer before docker image load."""
    try:
        indexes = {}
        blobs = {}
        sizes = {}
        with path.open("rb") as stream:
            reader = TarReader(stream, directories=frozenset({"blobs", "blobs/sha256"}))
            for member in reader.members():
                name = member.name
                if name in {"index.json", "oci-layout"}:
                    indexes[name] = strict_json(reader.small(member, name, MAX_INDEX))
                    continue
                if not re.fullmatch(r"blobs/sha256/[0-9a-f]{64}", name):
                    raise _reject()
                digest = "sha256:" + name.rsplit("/", 1)[1]
                sizes[digest] = member.size
                if member.size <= MAX_INDEX and len(blobs) < 128:
                    contents = reader.small(member, name, MAX_INDEX)
                    observed = digest_of(contents)
                    blobs[digest] = contents
                else:
                    observed = reader.copy(member)
                if observed != digest:
                    raise _reject()
        if indexes["oci-layout"] != {"imageLayoutVersion": "1.0.0"}:
            raise _reject()
        index = indexes["index.json"]
        (leaf,) = index["manifests"]
        os_name, architecture = platform.split("/")
        digest = reference.split("@")[1]
        alias = image_alias(reference)
        if (
            index["schemaVersion"] != 2
            or any(field in leaf for field in ("urls", "data", "artifactType"))
            or leaf["mediaType"] not in MANIFEST_TYPES
            or leaf["digest"] != digest
            or leaf["size"] != sizes[digest]
            or leaf["platform"] != {"os": os_name, "architecture": architecture}
            or leaf["annotations"] != {
                "io.containerd.image.name": alias,
                "org.opencontainers.image.ref.name": alias.rsplit(":", 1)[1],
            }
        ):
            raise _reject()
        manifest = strict_json(blobs[digest])
        if (
            manifest["schemaVersion"] != 2
            or manifest.get("mediaType", leaf["mediaType"]) != leaf["mediaType"]
            or "subject" in manifest or "artifactType" in manifest
        ):
            raise _reject()
        configuration = manifest["config"]
        layers = manifest["layers"]
        if not isinstance(layers, list) or len(layers) > 128:
            raise _reject()
        for descriptor, media in ((configuration, CONFIG_TYPES), *((layer, LAYER_TYPES) for layer in layers)):
            if (
                descriptor["mediaType"] not in media
                or any(field in descriptor for field in ("urls", "data"))
                or sizes[descriptor["digest"]] != descriptor["size"]
            ):
                raise _reject()
        config_id = configuration["digest"]
        if set(sizes) != {digest, config_id, *(layer["digest"] for layer in layers)}:
            raise _reject()
        config = strict_json(blobs[config_id])
        diff_ids = config["rootfs"]["diff_ids"]
        if (
            config["os"] != os_name or config["architecture"] != architecture
            or config["rootfs"]["type"] != "layers" or not isinstance(diff_ids, list)
            or len(diff_ids) != len(layers) or any(not DIGEST.fullmatch(item) for item in diff_ids)
        ):
            raise _reject()
    except (KeyError, TypeError, ValueError, UnicodeError, RecursionError, EOFError, tarfile.HeaderError):
        raise _reject() from None
    else:
        return config_id, diff_ids
