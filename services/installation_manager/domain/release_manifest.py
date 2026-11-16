"""Version one wire contract shared by release producers and the staging executor."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Annotated, Literal, Self

from packaging.version import Version
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from .operation_state import FailureReason

Digest = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]
ReleaseId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.+-]{0,127}$")]
VersionText = Annotated[
    str, StringConstraints(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+(?:-?rc[1-9][0-9]*)?$")
]
Revision = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{4,32}$")]
Platform = Annotated[str, StringConstraints(pattern=r"^linux/(amd64|arm64)$")]
ServiceName = Annotated[str, StringConstraints(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$")]
ImageReference = Annotated[
    str,
    StringConstraints(
        max_length=320,
        pattern=(
            r"^[a-z0-9][a-z0-9.-]*(?::[0-9]+)?"
            r"(?:/[a-z0-9]+(?:[._-]+[a-z0-9]+)*)+@sha256:[0-9a-f]{64}$"
        ),
    ),
]
GitSHA = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]
Signature = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{128}$")]
PublicKey = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
UtcDate = Annotated[
    str, StringConstraints(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
]
Positive = Annotated[int, Field(gt=0)]
NonNegative = Annotated[int, Field(ge=0)]
REQUIRED_SERVICES = frozenset(
    {
        "postgres",
        "valkey",
        "gateway",
        "migrate",
        "installation_manager",
        "orchestrator",
        "task-worker",
        "project-scheduler",
        "ui",
        "proxy",
    }
)


class StagingError(RuntimeError):
    def __init__(
        self, reason: FailureReason, problem: str, action: str, *, retryable: bool = False
    ) -> None:
        self.reason = reason
        self.retryable = retryable
        super().__init__(f"{problem}. {action}")


class WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class FileDescriptor(WireModel):
    url: Annotated[str, StringConstraints(min_length=1, max_length=2048)]
    digest: Digest
    size: Annotated[int, Field(gt=0, le=4 * 1024 * 1024)]


class ImageDescriptor(WireModel):
    reference: ImageReference
    compressed_bytes: Positive
    unpacked_bytes: Positive
    unpacked_inodes: Positive

    @model_validator(mode="after")
    def explicit_registry(self) -> Self:
        registry = self.reference.partition("/")[0]
        if "." not in registry and ":" not in registry:
            raise ValueError("Remote image references require an explicit registry")
        return self


class ResourceProfile(WireModel):
    min_cpus: Positive
    min_ram_bytes: Positive
    docker_reserve_bytes: NonNegative
    data_reserve_bytes: NonNegative
    temporary_bytes: Positive
    reserve_inodes: Positive
    max_task_workers: Positive


class Environment(WireModel):
    distributions: dict[str, Annotated[list[str], Field(min_length=1)]]
    min_docker: VersionText
    min_compose: VersionText
    pull_parallelism: Annotated[int, Field(ge=1, le=16)]
    base: ResourceProfile
    profiles: dict[Literal["ai-mcp"], ResourceProfile]


class Compatibility(WireModel):
    manager_version: VersionText
    executor_version: VersionText
    minimum_preparer_version: VersionText
    journal_format: Literal[1]


class IncomingTransition(WireModel):
    version: VersionText
    revision: Revision
    migration: Literal["from_revision", "none"]
    rollback: Literal["restore_backup", "compatible_apps"]


class Schema(WireModel):
    target_revision: Revision
    initial_install: bool
    from_releases: list[IncomingTransition]
    required_extensions: Annotated[list[ServiceName], Field(max_length=128)] = Field(
        default_factory=list
    )

    @model_validator(mode="after")
    def coherent_routes(self) -> Self:
        if len(set(self.required_extensions)) != len(self.required_extensions):
            raise ValueError("Duplicate required extension")
        routes: set[tuple[Version, str]] = set()
        for route in self.from_releases:
            key = (Version(route.version), route.revision)
            if key in routes or (route.migration == "none") != (
                route.revision == self.target_revision
            ):
                raise ValueError("Ambiguous or inconsistent migration route")
            if route.rollback == "compatible_apps" and route.migration != "none":
                raise ValueError("An application-only rollback requires an unchanged schema in v1")
            routes.add(key)
        return self


class PlatformRelease(WireModel):
    compose: FileDescriptor
    bootstrap: FileDescriptor
    images: Annotated[dict[ServiceName, ImageDescriptor], Field(min_length=1, max_length=128)]

    @model_validator(mode="after")
    def release_images(self) -> Self:
        if not self.images.keys() >= REQUIRED_SERVICES:
            raise ValueError("Required release images are missing")
        if self.images["gateway"] != self.images["migrate"]:
            raise ValueError("Gateway and migrator must use the same image descriptor")
        by_reference: dict[str, ImageDescriptor] = {}
        for image in self.images.values():
            if by_reference.setdefault(image.reference, image) != image:
                raise ValueError("One image has conflicting resource estimates")
        return self


class ReleaseManifest(WireModel):
    format_version: Literal[1]
    release_id: ReleaseId
    version: VersionText
    channel: Literal["stable", "rc"]
    backend_sha: GitSHA
    ui_sha: GitSHA
    issued_at: UtcDate
    expires_at: UtcDate
    platforms: Annotated[dict[Platform, PlatformRelease], Field(min_length=1)]
    environment: Environment
    compatibility: Compatibility
    database_schema: Schema = Field(alias="schema")

    @model_validator(mode="after")
    def coherent_release(self) -> Self:
        if Version(self.version).is_prerelease != (self.channel == "rc"):
            raise ValueError("Channel and release version disagree")
        if any(
            Version(route.version) >= Version(self.version)
            for route in self.database_schema.from_releases
        ):
            raise ValueError("An update source must precede the target version")
        if datetime.fromisoformat(self.issued_at) >= datetime.fromisoformat(self.expires_at):
            raise ValueError("Invalid manifest validity interval")
        return self


class SigningKey(WireModel):
    root_id: ReleaseId
    key_id: ReleaseId
    public_key: PublicKey
    valid_from: UtcDate
    valid_until: UtcDate


class SignedRelease(WireModel):
    payload: ReleaseManifest
    signing_key: SigningKey
    key_signature: Signature
    manifest_signature: Signature


def digest_of(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "ascii"
    )


def strict_json(content: bytes) -> object:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    return json.loads(content.decode("utf-8"), object_pairs_hook=reject_duplicates)
