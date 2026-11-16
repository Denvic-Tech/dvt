"""Operator actions and support records for the durable candidate journal."""

from __future__ import annotations

import contextlib
import os
import re
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..domain.operation_state import (
    ArtifactKind,
    Checkpoint,
    CheckpointOutcome,
    FailureReason,
    Operation,
    OperationKind,
    OperationStage,
    OwnershipConflict,
)
from ..host_bootstrap import atomic_write
from ..infrastructure.staging_artifacts import read_artifact

PREPARATION = {OperationStage.ADMITTED, OperationStage.PREPARING, OperationStage.PREPARED}
APPLY = {
    OperationStage.BACKUP, OperationStage.MIGRATING, OperationStage.APPLYING,
    OperationStage.VERIFYING, OperationStage.RESUMING,
}
SUPPORT_LIMIT = 16 * 1024
SERVICE_NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


class Action(StrEnum):
    RESUME = "resume"
    CANCEL_PREPARATION = "cancel_preparation"
    EXTEND_MAINTENANCE = "extend_maintenance"
    DEFER_MAINTENANCE = "defer_maintenance"
    RECOVER_MANAGER = "recover_manager"
    RETURN_TO_SOURCE = "return_to_source"


class MigrationState(StrEnum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    CORE_COMMITTED = "core_committed"
    TARGET_CONFIRMED = "target_confirmed"
    RESUMED = "resumed"
    UNKNOWN = "unknown"


def classify_migration(*, phase, revision, source, target, running, locked) -> MigrationState:
    if running or locked:
        return MigrationState.IN_PROGRESS
    if phase == "resumed" and revision == target:
        return MigrationState.RESUMED
    if phase == "done" and revision == target:
        return MigrationState.TARGET_CONFIRMED
    if phase == "core" and revision == target:
        return MigrationState.CORE_COMMITTED
    if phase is None and revision == source:
        return MigrationState.NOT_STARTED
    return MigrationState.UNKNOWN


class ServiceState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    service: str
    image_digest: str | None = None
    state: Literal["created", "running", "paused", "restarting", "removing", "exited", "dead"]
    health: Literal["starting", "healthy", "unhealthy"] | None = None


class SourceFailure(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: UUID
    stage: OperationStage
    occurred_at: datetime
    reason: FailureReason


class FilesystemState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    free_bytes: int = Field(ge=0)
    free_inodes: int = Field(ge=0)


class SupportObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    migration: MigrationState = MigrationState.UNKNOWN
    observed_at: datetime | None = None
    services: list[ServiceState] = Field(default_factory=list, max_length=128)
    compose_version: str | None = None
    filesystems: dict[Literal["data", "backup", "docker_root", "temporary"], FilesystemState] = (
        Field(default_factory=dict)
    )


def actions(operation: Operation, failure: FailureReason | None) -> list[Action]:
    stage = operation.stage
    kind = operation.request.kind
    if stage.terminal or kind is OperationKind.RESTORE:
        return []
    if kind is OperationKind.MANAGER_RECOVERY:
        return [Action.RESUME]
    if stage in PREPARATION:
        result = [Action.CANCEL_PREPARATION]
        if stage is OperationStage.PREPARED and kind is OperationKind.INSTALL:
            result.insert(0, Action.RESUME)
        return result
    if stage is OperationStage.MAINTENANCE:
        result = [Action.RESUME, Action.DEFER_MAINTENANCE]
        if failure is FailureReason.MAINTENANCE_DRAIN_TIMEOUT:
            result.insert(1, Action.EXTEND_MAINTENANCE)
        return result
    if stage in APPLY:
        result = []
        if failure not in {FailureReason.INCOMPATIBLE_SCHEMA, FailureReason.INVALID_PACKAGE}:
            result.append(Action.RESUME)
        if stage is OperationStage.BACKUP:
            result.append(Action.RETURN_TO_SOURCE)
        if stage in {OperationStage.APPLYING, OperationStage.VERIFYING, OperationStage.RESUMING}:
            result.append(Action.RECOVER_MANAGER)
        return result
    return []


def last_failure(events, *, stage: OperationStage) -> FailureReason | None:
    for event in reversed(events):
        if (
            event.stage is stage and event.checkpoint is not None
            and event.checkpoint.reason is not None
        ):
            return event.checkpoint.reason
    return None


def _support_path(store, operation_id) -> Path:
    return store.artifact_path(ArtifactKind.STAGING, operation_id) / "support-observation.json"


def read_observation(store, operation_id) -> SupportObservation | None:
    try:
        raw = read_artifact(_support_path(store, operation_id), SUPPORT_LIMIT)
        if raw is None:
            return None
        value = SupportObservation.model_validate_json(raw)
    except (OSError, RuntimeError, ValueError, ValidationError):
        return None
    if (
        (value.compose_version is not None and not re.fullmatch(
            r"v?[0-9]+\.[0-9]+\.[0-9]+(?:[-+.][a-zA-Z0-9.-]{1,24})?", value.compose_version
        ))
        or any(
            not SERVICE_NAME.fullmatch(row.service)
            or (row.image_digest is not None and not DIGEST.fullmatch(row.image_digest))
            for row in value.services
        )
    ):
        return None
    return value


def save_observation(
    directory: Path,
    migration: MigrationState,
    containers: dict[str, list[dict]],
    images: dict[str, str],
    compose_version: str | None,
    config: dict,
) -> None:
    references = {image: ref.rsplit("@", 1)[-1] for ref, image in images.items()}
    states = [
        ServiceState(
            service=role,
            image_digest=references.get(row["Image"]),
            state=row["State"]["Status"],
            health=(row["State"].get("Health") or {}).get("Status"),
        )
        for role, rows in sorted(containers.items()) if SERVICE_NAME.fullmatch(role)
        for row in rows
    ][:128]
    filesystems = {}
    if os.name == "posix":
        for key in ("data", "backup", "docker_root", "temporary"):
            with contextlib.suppress(OSError):
                usage = os.statvfs(config[key])
                filesystems[key] = FilesystemState(
                    free_bytes=usage.f_bavail * usage.f_frsize, free_inodes=usage.f_favail,
                )
    value = SupportObservation(
        migration=migration, observed_at=datetime.now(UTC), services=states,
        compose_version=compose_version, filesystems=filesystems,
    )
    atomic_write(directory / "support-observation.json", value.model_dump_json().encode())


def restore_actions(store, operation: Operation) -> list[Action] | None:
    if operation.stage.terminal:
        return None
    directory = store.artifact_path(ArtifactKind.STAGING, operation.id)
    if not (directory / "restored-data.json").exists():
        return None
    return [Action.RESUME] if (directory / "restore-authorization.json").exists() else []


def import_source_failure(content: bytes, operation: Operation) -> SourceFailure:
    from ..domain.release_manifest import strict_json

    document = strict_json(content)
    snapshot = document["snapshot"]["operation"]
    event = document["first_failure"]
    release = operation.request.release
    if (
        document["format_version"] != 1
        or snapshot["id"] != str(operation.id)
        or snapshot["instance_id"] != str(operation.instance_id)
        or snapshot["request"]["release"] != {
            "release_id": release.release_id, "manifest_digest": release.manifest_digest,
        }
        or event["kind"] != "checkpoint"
        or event["operation_id"] != str(operation.id)
    ):
        raise ValueError("The source diagnostics belong to another operation")
    occurred = datetime.fromisoformat(event["occurred_at"])
    if occurred.tzinfo is None:
        raise ValueError("The source failure date must include a timezone")
    value = SourceFailure(
        operation_id=UUID(event["operation_id"]),
        stage=OperationStage(event["stage"]),
        reason=FailureReason(event["checkpoint"]["reason"]),
        occurred_at=occurred.astimezone(UTC),
    )
    if not operation.admitted_at <= value.occurred_at <= datetime.now(UTC):
        raise ValueError("The source failure date is outside the operation")
    return value


def read_source_failure(store, operation_id) -> SourceFailure | None:
    directory = store.artifact_path(ArtifactKind.STAGING, operation_id)
    try:
        raw = read_artifact(directory / "source-failure.json", SUPPORT_LIMIT)
        if raw is not None:
            value = SourceFailure.model_validate_json(raw)
            if value.operation_id == operation_id:
                return value
    except (OSError, RuntimeError, ValueError):
        pass
    return None


def cancel_preparation(store, operation_id) -> None:
    with contextlib.suppress(OwnershipConflict), store.claim(operation_id) as owner:
        operation = store.get(operation_id)
        if operation.stage not in PREPARATION or operation.request.kind not in {
            OperationKind.INSTALL, OperationKind.UPDATE,
        }:
            return
        owner.checkpoint(Checkpoint(OperationStage.CANCELLED, CheckpointOutcome.VERIFIED))


def main() -> int:
    import argparse
    import sys
    from dataclasses import asdict

    from ..domain.release_manifest import canonical_json
    from ..host_bootstrap import STATE, safe_path
    from ..infrastructure.operation_store import OperationStore

    parser = argparse.ArgumentParser(description="Export the protected original failure by ID")
    parser.add_argument("--dir", required=True, type=Path)
    parser.add_argument("--operation-id", required=True, type=UUID)
    args = parser.parse_args()
    try:
        if os.geteuid():
            raise ValueError("Root is required")
        data = safe_path(args.dir)
        if not safe_path(data / STATE / "journal.sqlite3").is_file():
            raise ValueError("The protected journal is missing")
        store = OperationStore.for_host(data)
        identity = store.identity()
        operation = store.get(args.operation_id)
        failure = store.first_failure(args.operation_id)
        if (
            identity is None or identity.data_dir != str(data)
            or operation is None or failure is None
        ):
            raise ValueError("No original failure for this operation")
        # The schema is shared with the authenticated web command. Export only the
        # typed operation and earliest failure so it can be retained with the copy.
        payload = {
            "format_version": 1,
            "snapshot": {"operation": asdict(operation)},
            "first_failure": asdict(failure),
        }
        import json

        sys.stdout.buffer.write(
            canonical_json(json.loads(json.dumps(payload, default=str))) + b"\n"
        )
    except (OSError, ValueError, RuntimeError):
        sys.stderr.write("Could not export the original failure from the protected journal\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
