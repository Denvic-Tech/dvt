"""Version-independent types for durable installation state."""

from __future__ import annotations

import ipaddress
import posixpath
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from urllib.parse import urlsplit
from uuid import UUID


def _validate_digest(value: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
        raise ValueError("Expected a canonical SHA-256 digest")


def _validate_uuid(value: UUID) -> None:
    if not isinstance(value, UUID) or not value.int:
        raise ValueError("Expected a nonzero UUID")


def _validate_port(value: int) -> None:
    if type(value) is not int or not 1 <= value <= 65535:
        raise ValueError("Expected a TCP port between 1 and 65535")


def _public_origin(value: str) -> str:
    if not isinstance(value, str) or any(
        char.isspace() or ord(char) < 32 or char in "?#\\" for char in value
    ):
        raise ValueError("Expected a public HTTP(S) origin")
    try:
        url = urlsplit(value)
        port = url.port
        if (
            url.scheme not in ("http", "https")
            or url.path not in ("", "/")
            or url.username is not None
            or not url.hostname
        ):
            raise ValueError
        host = url.hostname
        if ":" in host:
            host = f"[{ipaddress.IPv6Address(host).compressed}]"
        elif not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9.])?", host):
            raise ValueError
        if port is not None:
            _validate_port(port)
    except ValueError:
        raise ValueError("Expected a public HTTP(S) origin") from None
    origin = f"{url.scheme}://{host}"
    default_port = 443 if url.scheme == "https" else 80
    return f"{origin}:{port}" if port is not None and port != default_port else origin


@dataclass(frozen=True)
class InstanceIdentity:
    instance_id: UUID
    data_dir: str
    compose_project: str
    manager_address: str
    manager_port: int
    public_url: str

    def __post_init__(self) -> None:
        _validate_uuid(self.instance_id)
        if (
            not isinstance(self.data_dir, str)
            or not self.data_dir.startswith("/")
            or self.data_dir.startswith("//")
            or self.data_dir == "/"
            or any(ord(char) < 32 for char in self.data_dir)
            or self.data_dir != posixpath.normpath(self.data_dir)
        ):
            raise ValueError("Expected a canonical Linux host data path")
        if not isinstance(self.compose_project, str) or not re.fullmatch(
            r"[a-z0-9][a-z0-9_-]{0,127}", self.compose_project
        ):
            raise ValueError("Invalid Compose project name")
        try:
            if not isinstance(self.manager_address, str) or "%" in self.manager_address:
                raise ValueError
            address = ipaddress.ip_address(self.manager_address).compressed
        except ValueError:
            raise ValueError("Expected a master bind IP address") from None
        _validate_port(self.manager_port)
        object.__setattr__(self, "manager_address", address)
        object.__setattr__(self, "public_url", _public_origin(self.public_url))


class OperationKind(StrEnum):
    INSTALL = "install"
    UPDATE = "update"
    MANAGER_RECOVERY = "manager_recovery"
    RESTORE = "restore"


@dataclass(frozen=True)
class ReleasePin:
    release_id: str
    manifest_digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.release_id, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.+-]{0,127}", self.release_id
        ):
            raise ValueError("Invalid release identifier")
        _validate_digest(self.manifest_digest)


@dataclass(frozen=True)
class OperationRequest:
    kind: OperationKind
    release: ReleasePin
    ai_mcp_enabled: bool | None = None
    task_workers_count: int | None = None
    app_port: int | None = None
    bundle_id: UUID | None = None
    restore_backup_id: UUID | None = None
    config_id: UUID | None = None

    def __post_init__(self) -> None:
        if type(self.kind) is not OperationKind or type(self.release) is not ReleasePin:
            raise ValueError("Expected a typed operation kind and pinned release")
        if self.ai_mcp_enabled is not None and type(self.ai_mcp_enabled) is not bool:
            raise ValueError("Expected a Boolean AI MCP setting")
        if self.task_workers_count is not None and (
            type(self.task_workers_count) is not int or self.task_workers_count < 1
        ):
            raise ValueError("Expected a positive worker count")
        if self.app_port is not None:
            _validate_port(self.app_port)
        for artifact_id in (self.bundle_id, self.restore_backup_id, self.config_id):
            if artifact_id is not None:
                _validate_uuid(artifact_id)


class ArtifactKind(StrEnum):
    BUNDLE = "bundle"
    STAGING = "staging"
    BACKUP = "backup"
    CONFIG = "config"


class OperationStage(StrEnum):
    ADMITTED = "admitted"
    PREPARING = "preparing"
    PREPARED = "prepared"
    MAINTENANCE = "maintenance"
    BACKUP = "backup"
    MIGRATING = "migrating"
    APPLYING = "applying"
    VERIFYING = "verifying"
    RESUMING = "resuming"
    RECOVERY_REQUIRED = "recovery_required"
    RECOVERING = "recovering"
    SUCCEEDED = "succeeded"
    CANCELLED = "cancelled"
    FAILED = "failed"

    @property
    def terminal(self) -> bool:
        return self in (self.SUCCEEDED, self.CANCELLED, self.FAILED)


_TRANSITIONS = {
    OperationStage.ADMITTED: {
        OperationStage.PREPARING,
        OperationStage.CANCELLED,
        OperationStage.FAILED,
    },
    OperationStage.PREPARING: {
        OperationStage.PREPARED,
        OperationStage.CANCELLED,
        OperationStage.FAILED,
    },
    OperationStage.PREPARED: {
        OperationStage.CANCELLED,
        OperationStage.FAILED,
        OperationStage.MAINTENANCE,
        OperationStage.MIGRATING,
        OperationStage.RECOVERING,
    },
    OperationStage.MAINTENANCE: {
        OperationStage.BACKUP,
        OperationStage.CANCELLED,
        OperationStage.RECOVERY_REQUIRED,
    },
    OperationStage.BACKUP: {
        OperationStage.MIGRATING,
        OperationStage.CANCELLED,
        OperationStage.RECOVERY_REQUIRED,
    },
    OperationStage.MIGRATING: {OperationStage.APPLYING, OperationStage.RECOVERY_REQUIRED},
    OperationStage.APPLYING: {OperationStage.VERIFYING, OperationStage.RECOVERY_REQUIRED},
    OperationStage.VERIFYING: {OperationStage.RESUMING, OperationStage.RECOVERY_REQUIRED},
    OperationStage.RESUMING: {OperationStage.SUCCEEDED, OperationStage.RECOVERY_REQUIRED},
    OperationStage.RECOVERY_REQUIRED: {OperationStage.RECOVERING},
    OperationStage.RECOVERING: {
        OperationStage.MIGRATING,
        OperationStage.APPLYING,
        OperationStage.VERIFYING,
        OperationStage.RESUMING,
        OperationStage.RECOVERY_REQUIRED,
    },
}


class CheckpointOutcome(StrEnum):
    PROGRESS = "progress"
    VERIFIED = "verified"
    RETRYABLE_ERROR = "retryable_error"
    BLOCKED = "blocked"


class FailureReason(StrEnum):
    DISTRIBUTOR_UNAVAILABLE = "distributor_unavailable"
    REGISTRY_UNAVAILABLE = "registry_unavailable"
    TLS = "tls"
    DISK_SPACE = "disk_space"
    INODES = "inodes"
    INCOMPATIBLE_RELEASE = "incompatible_release"
    INVALID_PACKAGE = "invalid_package"
    COMPOSE = "compose"
    DATABASE_UNAVAILABLE = "database_unavailable"
    MIGRATION = "migration"
    INCOMPATIBLE_SCHEMA = "incompatible_schema"
    GATEWAY_UNAVAILABLE = "gateway_unavailable"
    PROFILE_UNHEALTHY = "profile_unhealthy"
    BACKUP = "backup"
    MANAGER_UNAVAILABLE = "manager_unavailable"


@dataclass(frozen=True)
class Observation:
    source_digest: str | None = None
    target_digest: str | None = None
    observed_digest: str | None = None
    source_revision: str | None = None
    target_revision: str | None = None
    observed_revision: str | None = None
    staging_id: UUID | None = None
    backup_id: UUID | None = None

    def __post_init__(self) -> None:
        for digest in (self.source_digest, self.target_digest, self.observed_digest):
            if digest is not None:
                _validate_digest(digest)
        for revision in (self.source_revision, self.target_revision, self.observed_revision):
            if revision is not None and (
                not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{4,32}", revision)
            ):
                raise ValueError("Invalid schema revision")
        for artifact_id in (self.staging_id, self.backup_id):
            if artifact_id is not None:
                _validate_uuid(artifact_id)


@dataclass(frozen=True)
class Checkpoint:
    stage: OperationStage
    outcome: CheckpointOutcome = CheckpointOutcome.PROGRESS
    reason: FailureReason | None = None
    observation: Observation = Observation()

    def __post_init__(self) -> None:
        if (
            type(self.stage) is not OperationStage
            or type(self.outcome) is not CheckpointOutcome
            or type(self.observation) is not Observation
        ):
            raise ValueError("Expected a typed checkpoint")
        failed = self.outcome in (CheckpointOutcome.RETRYABLE_ERROR, CheckpointOutcome.BLOCKED)
        if (failed and type(self.reason) is not FailureReason) or (
            not failed and self.reason is not None
        ):
            raise ValueError("A failure reason is required only for error checkpoints")
        if (
            self.stage is OperationStage.SUCCEEDED
            and self.outcome is not CheckpointOutcome.VERIFIED
        ):
            raise ValueError("A successful completion requires a verified result")


@dataclass(frozen=True)
class OwnerRecord:
    claim_id: UUID
    claimed_at: datetime


@dataclass(frozen=True)
class Operation:
    id: UUID
    instance_id: UUID
    request: OperationRequest
    stage: OperationStage
    admitted_at: datetime
    stage_started_at: datetime
    finished_at: datetime | None
    last_owner: OwnerRecord | None
    observation: Observation


def transition_allowed(operation: Operation, checkpoint: Checkpoint) -> bool:
    source, target = operation.stage, checkpoint.stage
    if source.terminal or (source != target and target not in _TRANSITIONS[source]):
        return False

    kind = operation.request.kind
    if source is OperationStage.PREPARED:
        if target is OperationStage.MIGRATING:
            return kind is OperationKind.INSTALL
        if target is OperationStage.RECOVERING:
            return kind in (OperationKind.MANAGER_RECOVERY, OperationKind.RESTORE)

    if target is OperationStage.MIGRATING and kind is OperationKind.UPDATE:
        # The recovery point must already be committed when migration starts.
        backup_id = operation.observation.backup_id
        return backup_id is not None and checkpoint.observation.backup_id in (None, backup_id)

    if target is OperationStage.CANCELLED and source in (
        OperationStage.MAINTENANCE,
        OperationStage.BACKUP,
    ):
        return checkpoint.outcome is CheckpointOutcome.VERIFIED
    return True


class EventKind(StrEnum):
    ADMITTED = "admitted"
    OWNER_ACQUIRED = "owner_acquired"
    CHECKPOINT = "checkpoint"


@dataclass(frozen=True)
class OperationEvent:
    cursor: int
    operation_id: UUID
    kind: EventKind
    occurred_at: datetime
    stage: OperationStage
    owner: OwnerRecord | None
    checkpoint: Checkpoint | None = None
    previous_stage: OperationStage | None = None
    previous_stage_duration_ms: int | None = None


class IdentityConflict(ValueError):
    """The identity on disk differs from the proposed identity."""


class IdentityNotEstablished(RuntimeError):
    """Admission requires a persisted identity."""


class OperationConflict(RuntimeError):
    def __init__(self, operation_id: UUID) -> None:
        self.operation_id = operation_id
        super().__init__("An operation already holds the idempotency key or active reservation")


class OperationNotFound(LookupError):
    """The requested operation does not belong to this store."""


class OwnershipConflict(RuntimeError):
    """The instance lock is busy or the current claim cannot change this operation."""


class InvalidTransition(ValueError):
    """The operation cannot enter the requested stage from its current stage."""
