"""Run the window and commit a verified recovery point without changing the schema."""

from __future__ import annotations

import contextlib
import sqlite3
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from ..domain.operation_state import (
    ArtifactKind,
    Checkpoint,
    CheckpointOutcome,
    FailureReason,
    Observation,
    OperationKind,
    OperationStage,
    OwnershipConflict,
)
from ..domain.release_manifest import StagingError, canonical_json, strict_json
from ..host_bootstrap import atomic_write, safe_path
from ..infrastructure.maintenance_archive import create_copy, preflight
from ..infrastructure.maintenance_database import (
    close_sql,
    drain_sql,
    frozen_sql,
    open_for_defer_sql,
    reopen_sql,
)
from ..infrastructure.maintenance_host import ComposeMaintenanceHost, MaintenancePrerequisite
from ..infrastructure.offline_host import local_trust, offline_ready
from ..infrastructure.operation_store import OperationStore
from ..infrastructure.staging_artifacts import artifact_directory, read_artifact, write_artifact
from ..infrastructure.staging_commands import Deadline, RetryPolicy
from ..infrastructure.staging_docker import StagingDocker
from ..logger import logger

DRAIN_SECONDS = 300
DRAIN_POLL_SECONDS = 2
ARTIFACT_LIMIT = 256 * 1024
MAINTENANCE_STAGES = (OperationStage.PREPARED, OperationStage.MAINTENANCE, OperationStage.BACKUP)


def _read(path: Path) -> dict | None:
    value = read_artifact(path, ARTIFACT_LIMIT)
    return strict_json(value) if value is not None else None


def _save(path: Path, value: dict) -> None:
    write_artifact(path, canonical_json(value))


@dataclass(frozen=True, slots=True)
class MaintenanceBackup:
    store: OperationStore
    config: dict

    def execute(
        self, operation_id: UUID, *, confirm: bool = False, extend: bool = False, defer: bool = False
    ) -> None:
        with contextlib.suppress(OwnershipConflict), self.store.claim(operation_id) as owner:
            operation = self.store.get(operation_id)
            if (
                operation is None
                or operation.request.kind is not OperationKind.UPDATE
                or operation.instance_id != UUID(self.config["instance"])
                or operation.stage not in MAINTENANCE_STAGES
            ):
                raise ValueError("This operation cannot enter the update maintenance window")
            stage = operation.stage
            if stage is OperationStage.PREPARED and not confirm:
                return
            error = FailureReason.INCOMPATIBLE_RELEASE
            try:
                staging = artifact_directory(self.store, ArtifactKind.STAGING, operation_id)
                plan = _read(staging / "plan.json")
                revision = operation.observation.source_revision
                if (
                    plan is None
                    or plan["format_version"] != 1
                    or operation.observation.staging_id != operation_id
                    or plan["manifest_digest"] != operation.request.release.manifest_digest
                    or plan["config_id"] != str(operation.request.config_id)
                    or plan["applied_manifest_digest"] != operation.observation.source_digest
                    or operation.observation.source_digest is None
                    or not plan["transition"]
                    or revision is None
                    or plan["observed_revision"] != revision
                ):
                    raise MaintenancePrerequisite("A verified source and staged transition are required")
                host = ComposeMaintenanceHost(self.config, operation_id, plan["observed_images"])
                backup = safe_path(self.config["backup"])
                temporary = safe_path(self.config["temporary"])
                if stage is OperationStage.PREPARED and operation.request.bundle_id is not None:
                    offline_ready(
                        operation, self.store, self.config, plan,
                        local_trust(host.data, plan["trust"]),
                        StagingDocker(staging, Path("/root/.docker")),
                        Deadline(RetryPolicy(), temporary),
                    )
                settings_path = staging / "maintenance.json"
                saved = _read(settings_path)
                if saved is None:
                    if stage is not OperationStage.PREPARED:
                        raise MaintenancePrerequisite("The recorded source container plan is missing")
                    if defer or extend:
                        raise MaintenancePrerequisite("The maintenance window has not been started")
                    containers = host.capture(revision)
                    layout = preflight(host.data, backup, temporary, host.pgdata)
                    saved = {
                        "operation_id": str(operation_id),
                        "instance_id": str(operation.instance_id),
                        "source_revision": revision,
                        "source_digest": operation.observation.source_digest,
                        "source_images": plan["observed_images"],
                        "compose_project": self.config["project"],
                        "profiles": plan["profiles"],
                        "containers": containers,
                        "layout": layout,
                        "backup_id": str(operation_id),
                        "schedule_policy": "skip_cron_preserve_existing_retries",
                        "queue_policy": "drain_admitted_cancel_unadmitted_roots",
                    }
                    _save(settings_path, saved)
                pg = host.validate(saved["containers"], revision)
                if (
                    host.pgdata.relative_to(host.data).as_posix() != saved["layout"]["postgres_data"]
                    or (
                        backup.stat().st_dev not in {host.data.stat().st_dev, host.pgdata.stat().st_dev}
                    ) != saved["layout"]["separate_filesystem"]
                ):
                    raise MaintenancePrerequisite("The prepared data or backup filesystem changed")

                if stage is OperationStage.PREPARED:
                    owner.checkpoint(Checkpoint(OperationStage.MAINTENANCE))
                    stage = OperationStage.MAINTENANCE

                if stage is OperationStage.MAINTENANCE:
                    defer_path = staging / "maintenance-defer.json"
                    if defer or _read(defer_path) is not None:
                        if host.sql(pg, open_for_defer_sql(operation_id)) != "safe":
                            raise MaintenancePrerequisite("A frozen window cannot be deferred here")
                        _save(defer_path, {"operation_id": str(operation_id)})
                        if host.sql(pg, reopen_sql(operation_id)) != "open":
                            raise MaintenancePrerequisite("The admission gate did not reopen")
                        owner.checkpoint(Checkpoint(OperationStage.CANCELLED, CheckpointOutcome.VERIFIED))
                        return

                    deadline_path = staging / "maintenance-deadline.json"
                    deadline = _read(deadline_path)
                    if deadline is None or extend:
                        deadline = {"until": int(time.time()) + DRAIN_SECONDS}
                        atomic_write(deadline_path, canonical_json(deadline))
                    error = FailureReason.DATABASE_UNAVAILABLE
                    if host.sql(pg, close_sql(operation_id)) != str(operation_id):
                        raise MaintenancePrerequisite("Another operation owns task admission")
                    while True:
                        status = host.sql(pg, drain_sql(operation_id))
                        if status == "frozen":
                            owner.checkpoint(Checkpoint(OperationStage.BACKUP))
                            stage = OperationStage.BACKUP
                            break
                        if not status.isdecimal():
                            raise MaintenancePrerequisite("The operation does not own task admission")
                        if time.time() >= deadline["until"]:
                            owner.checkpoint(
                                Checkpoint(
                                    stage, CheckpointOutcome.RETRYABLE_ERROR,
                                    FailureReason.MAINTENANCE_DRAIN_TIMEOUT,
                                )
                            )
                            logger.warning(
                                "Maintenance wait elapsed: %s tasks remain. Extend or defer.",
                                status,
                            )
                            return
                        time.sleep(DRAIN_POLL_SECONDS)
                elif defer or extend:
                    raise MaintenancePrerequisite("The window already froze all task admission")

                error = FailureReason.BACKUP
                if host.sql(pg, frozen_sql(operation_id)) != "frozen":
                    raise MaintenancePrerequisite("The persisted task gate is not frozen")
                host.stop_writers(saved["containers"])
                pg = host.assert_frozen(saved["containers"], revision)
                metadata = {"format_version": 1, **saved}
                create_copy(
                    backup, operation_id, metadata, host, pg,
                    confirm_source_sealed=lambda: host.assert_frozen(saved["containers"], revision),
                )
                if operation.observation.backup_id is None:
                    owner.checkpoint(
                        Checkpoint(
                            OperationStage.BACKUP,
                            CheckpointOutcome.VERIFIED,
                            observation=Observation(backup_id=operation_id),
                        )
                    )
            except MaintenancePrerequisite as exc:
                owner.checkpoint(Checkpoint(stage, CheckpointOutcome.BLOCKED, error))
                # All messages in this exception come from fixed, secret-free checks.
                logger.warning("%s", exc)
            except StagingError as failure:
                outcome = (
                    CheckpointOutcome.RETRYABLE_ERROR if failure.retryable
                    else CheckpointOutcome.BLOCKED
                )
                owner.checkpoint(Checkpoint(stage, outcome, failure.reason))
                logger.warning("Maintenance paused at %s: %s", stage.value, failure.reason.value)
            except (
                OSError, RuntimeError, ValueError, KeyError, TypeError,
                subprocess.SubprocessError, sqlite3.Error,
            ):
                owner.checkpoint(Checkpoint(stage, CheckpointOutcome.RETRYABLE_ERROR, error))
                # Do not emit Docker/SQL stderr, mount names, env values or credentials.
                logger.warning("Maintenance paused at %s: %s", stage.value, error.value)
