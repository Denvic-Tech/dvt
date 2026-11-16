"""Apply only the previously verified release, preserving update admission on failure."""

from __future__ import annotations

import contextlib
import sqlite3
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from packaging.version import Version

from ..domain.operation_state import (
    ArtifactKind,
    Checkpoint,
    CheckpointOutcome,
    FailureReason,
    Observation,
    Operation,
    OperationKind,
    OperationStage,
    OwnershipConflict,
)
from ..domain.release_manifest import (
    REQUIRED_SERVICES,
    StagingError,
    canonical_json,
    digest_of,
    strict_json,
)
from ..host_bootstrap import (
    CONTROL,
    apply_manager,
    atomic_write,
    check_image,
    docker,
    init_container,
    safe_path,
)
from ..infrastructure.application_host import (
    CONTEXT_ENV,
    DATABASE_ID,
    MANAGED_ROLES,
    ApplyError,
    ComposeApplicationHost,
)
from ..infrastructure.maintenance_archive import verify_copy
from ..infrastructure.maintenance_database import confirm_return_to_source_sql, frozen_sql
from ..infrastructure.maintenance_host import PG_TARGET, ComposeMaintenanceHost
from ..infrastructure.operation_store import FORMAT_VERSION, OperationStore
from ..infrastructure.release_verification import MAX_MANIFEST_BYTES, TrustPolicy, verify_file
from ..infrastructure.staging_artifacts import (
    artifact_directory,
    load_config,
    read_artifact,
    write_artifact,
)
from ..infrastructure.staging_commands import Deadline, RetryPolicy
from ..infrastructure.staging_compose import (
    COMPOSE_LIMIT,
    DATABASE_ENV,
    check_model,
    compare_project,
    effective_config,
    validate_template,
)
from ..infrastructure.staging_docker import StagingDocker, _compose_value
from ..infrastructure.staging_host import selected_profile
from ..logger import logger
from .recovery import MigrationState, classify_migration, save_observation

APPLY_STAGES = {
    OperationStage.PREPARED,
    OperationStage.BACKUP,
    OperationStage.MIGRATING,
    OperationStage.APPLYING,
    OperationStage.VERIFYING,
    OperationStage.RESUMING,
}
LIMIT = 256 * 1024
MOUNTED_APP_DIRS = {"/app/installation", "/app/extensions"}


def _artifact(path: Path, limit: int = LIMIT) -> bytes:
    content = read_artifact(path, limit)
    if content is None:
        raise ApplyError(FailureReason.INVALID_PACKAGE, "A verified staging artifact is missing")
    return content


def _compose_literal(value):
    # Compose interpolates arbitrary string fields, even from a resolved JSON file.
    if isinstance(value, str):
        return value.replace("$", "$$")
    if isinstance(value, list):
        return [_compose_literal(item) for item in value]
    if isinstance(value, dict):
        return {key: _compose_literal(item) for key, item in value.items()}
    return value


def _dotenv(environment: dict[str, str]) -> bytes:
    def quote(value: str) -> str:
        return value.replace("\\", "\\\\").replace("'", "\\'")

    return "".join(
        f"{name}='{quote(value)}'\n" for name, value in sorted(environment.items())
    ).encode()


def _validate_runtime(model: dict) -> None:
    services = model["services"]
    migrate, gateway, postgres = (services[name] for name in ("migrate", "gateway", "postgres"))
    leases = services["installation_manager"].get("depends_on", {})
    if (
        migrate.get("command") != ["python3", "-m", "services.gateway.migrate"]
        or migrate.get("entrypoint")
        or migrate.get("ports")
        or migrate.get("restart") != "no"
        or migrate.get("privileged")
        or migrate.get("deploy")
        or migrate.get("profiles")
        or set(migrate.get("depends_on", {})) != {"postgres"}
        or migrate["depends_on"]["postgres"]["condition"] != "service_healthy"
        or not postgres.get("healthcheck", {}).get("test")
        or postgres.get("ports")
        or len(postgres.get("volumes", [])) != 1
        or postgres["volumes"][0]["type"] != "bind"
        or postgres["volumes"][0]["target"] != PG_TARGET
        or postgres["volumes"][0].get("read_only")
        or migrate.get("volumes") != gateway.get("volumes")
        or {mount["target"] for mount in (migrate.get("volumes") or [])} != MOUNTED_APP_DIRS
        or any(mount["type"] != "bind" for mount in migrate["volumes"])
        or migrate.get("networks") != gateway.get("networks")
        or any(
            not services[name].get("healthcheck", {}).get("test")
            for name in ("gateway", "ui", "valkey")
        )
        or leases
    ):
        raise ApplyError(
            FailureReason.COMPOSE,
            "Compose does not provide an independent manager and private migrator",
        )

    pg_env = postgres["environment"]
    gateway_connection = {
        key: val
        for key, val in gateway["environment"].items()
        if key in DATABASE_ENV and key.startswith("POSTGRES_")
    }
    for name in MANAGED_ROLES:
        role = services[name]
        if name != "migrate" and (
            role.get("depends_on", {}).get("migrate", {}).get("condition")
            != "service_completed_successfully"
        ):
            raise ApplyError(
                FailureReason.COMPOSE, "An application role can start before migration"
            )
        env = role.get("environment") or {}
        if (
            not all(
                pg_env.get(key) and env.get(key) == pg_env[key]
                for key in ("POSTGRES_USER", "POSTGRES_DB", "POSTGRES_PASSWORD")
            )
            or any(env.get(key) != value for key, value in gateway_connection.items())
            or env.get("POSTGRES_HOST", "postgres") != "postgres"
            or env.get("POSTGRES_PORT", "5432") != "5432"
        ):
            raise ApplyError(
                FailureReason.COMPOSE, "A role refers to a different PostgreSQL database"
            )

    for role in services.keys() - REQUIRED_SERVICES:
        if not services[role].get("healthcheck", {}).get("test"):
            raise ApplyError(FailureReason.COMPOSE, "An additional service has no readiness probe")
    enabled = "dvt-ai-mcp" in services
    if (
        str(services["proxy"].get("environment", {}).get("DVT_AI_MCP_ENABLED", "false")).lower()
        != str(enabled).lower()
    ):
        raise ApplyError(
            FailureReason.COMPOSE, "The public AI MCP route differs from the staged profile"
        )


@dataclass(frozen=True)
class ApplicationApply:
    store: OperationStore
    config: dict
    probe_manager: Callable[[dict, OperationStore, UUID, UUID], None]

    def _staged(self, operation: Operation, directory: Path):
        identity = self.store.identity()
        observation = operation.observation
        pin = operation.request.release
        plan = strict_json(_artifact(directory / "plan.json"))
        signed = _artifact(directory / "manifest.json", MAX_MANIFEST_BYTES)
        if (
            identity.instance_id != UUID(self.config["instance"])
            or identity.instance_id != operation.instance_id
            or identity.compose_project != self.config["project"]
            or identity.data_dir != self.config["data"]
            or plan["format_version"] != 1
            or plan["config_id"] != str(operation.request.config_id)
            or plan["manifest_digest"] != digest_of(signed)
            or plan["manifest_digest"] != pin.manifest_digest
            or plan["release_id"] != pin.release_id
            or observation.staging_id != operation.id
            or observation.target_digest != pin.manifest_digest
            or plan["target_revision"] != observation.target_revision
            or plan["observed_revision"] != observation.source_revision
            or plan["applied_manifest_digest"] != observation.source_digest
        ):
            raise ApplyError(
                FailureReason.INVALID_PACKAGE, "The operation and verified staging disagree"
            )
        policy = read_artifact(Path(identity.data_dir) / CONTROL / "release-trust.json", LIMIT)
        trust = TrustPolicy.from_document(
            strict_json(policy) if policy is not None else plan["trust"]
        )
        authorization_path = directory / "apply-authorization.json"
        raw = read_artifact(authorization_path, LIMIT)
        verified_at = datetime.now(UTC)
        authorization = {
            "instance": str(operation.instance_id),
            "operation": str(operation.id),
            "manifest": pin.manifest_digest,
        }
        if raw is not None:
            saved = strict_json(raw)
            previous = datetime.fromisoformat(saved.pop("verified_at"))
            if saved != authorization or previous.tzinfo != UTC or previous > verified_at:
                raise ApplyError(
                    FailureReason.INVALID_PACKAGE, "The recorded release authorization is invalid"
                )
        historical = False
        try:
            release = trust.verify(signed, pin, now=verified_at)
        except StagingError:
            if raw is None or operation.stage in {OperationStage.PREPARED, OperationStage.BACKUP}:
                raise
            # Even a continuation must satisfy the current roots/revocation policy.
            # Expiry alone can be set aside only after observing a completed receipt.
            release = trust.verify(signed, pin, now=previous)
            historical = True
        distribution = release.platforms[plan["platform"]]
        schema = release.database_schema
        if (
            release.release_id != pin.release_id
            or schema.target_revision != plan["target_revision"]
        ):
            raise ApplyError(
                FailureReason.INVALID_PACKAGE, "The signed schema differs from the operation"
            )
        if operation.request.kind is OperationKind.INSTALL:
            if (
                not schema.initial_install
                or plan["transition"] is not None
                or observation.source_revision is not None
            ):
                raise ApplyError(
                    FailureReason.INCOMPATIBLE_SCHEMA, "The release does not authorize installation"
                )
        elif (
            observation.backup_id != operation.id
            or observation.source_revision is None
            or plan["transition"]
            not in [route.model_dump(mode="json") for route in schema.from_releases]
            or plan["transition"]["revision"] != observation.source_revision
            or Version(plan["transition"]["version"]) != Version(plan["observed_version"])
        ):
            raise ApplyError(
                FailureReason.BACKUP, "The operation lacks a verified update route or backup"
            )

        values = load_config(self.store, operation.request.config_id)
        values.pop("DVT_ALLOW_PRERELEASE", None)
        env, profiles = effective_config(
            values,
            identity,
            operation.request,
            release.version,
            release.environment.base.max_task_workers,
        )
        if (
            tuple(plan["profiles"]) != profiles
            or int(env["DVT_TASK_WORKERS_COUNT"])
            > selected_profile(release.environment, profiles).max_task_workers
        ):
            raise ApplyError(
                FailureReason.COMPOSE, "The selected profile differs from the staging plan"
            )
        compose = directory / "compose.yaml"
        content = _artifact(compose, COMPOSE_LIMIT)
        verify_file(content, distribution.compose, compose.name)
        validate_template(content)
        deadline = Deadline(RetryPolicy(), Path(self.config["temporary"]))
        docker = StagingDocker(directory, Path("/root/.docker"))
        model = docker.config(compose, identity.compose_project, profiles, env, deadline)
        full = docker.config(compose, identity.compose_project, ("*",), env, deadline)
        check_model(model, identity, distribution, env, active=True)
        check_model(full, identity, distribution, env, active=False)
        if plan["services"] != {
            name: entry["image"] for name, entry in model["services"].items()
        } or plan["model_digest"] != digest_of(canonical_json(model)):
            raise ApplyError(
                FailureReason.COMPOSE, "The effective Compose configuration changed after staging"
            )
        _validate_runtime(model)
        if operation.stage is OperationStage.PREPARED:
            observed = compare_project(
                model,
                identity,
                env,
                docker,
                None,
                deadline,
                bootstrap_image=plan["observed_images"].get("installation_manager"),
            )
            if (
                observed.image_references != plan["services"]
                or observed.source_images != plan["observed_images"]
            ):
                raise ApplyError(FailureReason.COMPOSE, "The initial project changed after staging")
        if raw is None:
            write_artifact(
                authorization_path,
                canonical_json({**authorization, "verified_at": verified_at.isoformat()}),
            )
        return release, plan, full, env, deadline, historical

    def _source(self, operation: Operation, plan: dict, directory: Path) -> dict:
        saved = strict_json(_artifact(directory / "maintenance.json"))
        if (
            saved["operation_id"] != str(operation.id)
            or saved["instance_id"] != str(operation.instance_id)
            or saved["backup_id"] != str(operation.id)
            or saved["source_revision"] != plan["observed_revision"]
            or saved["source_digest"] != plan["applied_manifest_digest"]
            or saved["source_images"] != plan["observed_images"]
            or saved["compose_project"] != self.config["project"]
        ):
            raise ApplyError(FailureReason.BACKUP, "The backup belongs to another source operation")
        return saved

    def _check_copy(self, operation: Operation, saved: dict, pg: str) -> None:
        host = ComposeMaintenanceHost(self.config, operation.id, saved["source_images"])
        verify_copy(
            safe_path(self.config["backup"]) / str(operation.id),
            {"format_version": 1, **saved},
            host,
            pg,
        )

    def _confirm_source(self, operation: Operation, plan: dict, saved: dict):
        data = Path(self.config["data"])
        applied = strict_json(_artifact(data / CONTROL / "current-release.json"))
        if (
            applied["manifest_digest"] != plan["applied_manifest_digest"]
            or applied["release_id"] != plan["applied_release_id"]
            or applied["instance"] != str(operation.instance_id)
            or applied["compose_digest"]
            != digest_of(_artifact(data / "docker-compose.yaml", 8 * COMPOSE_LIMIT))
            or applied["config_digest"] != digest_of(_artifact(data / ".env"))
        ):
            raise ApplyError(
                FailureReason.INCOMPATIBLE_RELEASE, "The committed source changed after staging"
            )
        host = ComposeMaintenanceHost(self.config, operation.id, saved["source_images"])
        pg = host.assert_frozen(saved["containers"], saved["source_revision"])
        if (
            host.pgdata != data / saved["layout"]["postgres_data"]
            or host.sql(pg, DATABASE_ID) != applied["database"]
        ):
            raise ApplyError(
                FailureReason.BACKUP, "The frozen database uses a different storage path"
            )
        self._check_copy(operation, saved, pg)
        if host.assert_frozen(saved["containers"], saved["source_revision"]) != pg:
            raise ApplyError(
                FailureReason.BACKUP, "The frozen database changed while verifying the copy"
            )
        return pg

    def _manager_images(self, operation: Operation, plan: dict) -> tuple[str, str]:
        directory = Path(self.config["data"]) / CONTROL
        source = plan["observed_images"].get("installation_manager")
        target = plan["services"]["installation_manager"]
        known = _artifact(directory / "current-manager").decode()
        if not source or known not in {source, target}:
            raise ApplyError(
                FailureReason.MANAGER_UNAVAILABLE, "The previous manager is not confirmed"
            )
        if operation.stage in {OperationStage.PREPARED, OperationStage.BACKUP} and known != source:
            raise ApplyError(
                FailureReason.MANAGER_UNAVAILABLE, "The current manager differs from the source"
            )
        for image in {source, target}:
            if init_container({**self.config, "manager": image}, "candidate-inspect") != str(
                FORMAT_VERSION
            ):
                raise ApplyError(
                    FailureReason.MANAGER_UNAVAILABLE, "A manager cannot read the active journal"
                )
        return source, target

    def _apply_manager_health(self, host, directory, images, operation, owner) -> None:
        source, target = images
        rows = host.containers().get("installation_manager", [])
        manager = rows[0] if rows else None
        target_running = manager is not None and host.is_target("installation_manager", manager)
        # If Compose stopped before replacing it, keep the functioning source visible.
        if manager is not None and not target_running and manager["State"]["Running"]:
            self.probe_manager(self.config, self.store, operation.id, owner.record.claim_id)
            raise ApplyError(
                FailureReason.MANAGER_UNAVAILABLE, "The target manager has not started"
            )
        try:
            if not target_running:
                raise ApplyError(
                    FailureReason.MANAGER_UNAVAILABLE, "The target manager is unavailable"
                )
            self.probe_manager(self.config, self.store, operation.id, owner.record.claim_id)
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
            apply_manager(self.config, source, directory / "manager-fallback.compose.yaml")
            self.probe_manager(self.config, self.store, operation.id, owner.record.claim_id)
            atomic_write(Path(self.config["data"]) / CONTROL / "current-manager", source.encode())
            raise ApplyError(
                FailureReason.MANAGER_UNAVAILABLE, "Restored the previous web manager"
            ) from None
        atomic_write(Path(self.config["data"]) / CONTROL / "current-manager", target.encode())

    @staticmethod
    def _support(host, directory: Path, migration: MigrationState) -> None:
        with contextlib.suppress(
            OSError, ValueError, RuntimeError, subprocess.SubprocessError,
        ):
            save_observation(
                directory, migration, host.containers(), host.image_ids,
                host.docker.compose_version(host.deadline), host.config,
            )

    def recover_manager(self, operation_id: UUID) -> None:
        with contextlib.suppress(OwnershipConflict), self.store.claim(operation_id) as owner:
            operation = self.store.get(operation_id)
            if (
                operation.request.kind not in {OperationKind.INSTALL, OperationKind.UPDATE}
                or operation.stage not in {
                    OperationStage.APPLYING, OperationStage.VERIFYING, OperationStage.RESUMING,
                }
            ):
                return
            try:
                self._recover_source_manager(operation, owner.record.claim_id)
            except (
                OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError,
            ):
                owner.checkpoint(
                    Checkpoint(
                        operation.stage, CheckpointOutcome.RETRYABLE_ERROR,
                        FailureReason.MANAGER_UNAVAILABLE,
                    )
                )
            else:
                owner.checkpoint(Checkpoint(operation.stage, CheckpointOutcome.VERIFIED))

    def _recover_source_manager(self, operation: Operation, claim_id: UUID) -> None:
        directory = artifact_directory(self.store, ArtifactKind.STAGING, operation.id)
        plan = strict_json(_artifact(directory / "plan.json"))
        source = plan["observed_images"]["installation_manager"]
        target = plan["services"]["installation_manager"]
        current = Path(self.config["data"]) / CONTROL / "current-manager"
        if (
            plan["manifest_digest"] != operation.request.release.manifest_digest
            or operation.observation.staging_id != operation.id
            or _artifact(current).decode() not in {source, target}
            or plan["target_revision"] != operation.observation.target_revision
        ):
            raise ApplyError(FailureReason.MANAGER_UNAVAILABLE, "The manager plan is unconfirmed")
        if init_container({**self.config, "manager": source}, "candidate-inspect") != str(
            FORMAT_VERSION
        ):
            raise ApplyError(FailureReason.MANAGER_UNAVAILABLE, "The previous manager is incompatible")
        allowed = {check_image(source)}
        with contextlib.suppress(OSError, ValueError, subprocess.SubprocessError):
            allowed.add(check_image(target))
        ids = docker(
            "container", "ls", "--all", "--quiet", "--no-trunc", "--filter",
            f"label=com.docker.compose.project={self.config['project']}", "--filter",
            "label=com.docker.compose.service=installation_manager",
        ).stdout.split()
        if len(ids) > 1:
            raise ApplyError(FailureReason.MANAGER_UNAVAILABLE, "The manager is ambiguous")
        if ids:
            (row,) = strict_json(docker("container", "inspect", ids[0]).stdout.encode())
            if row["Image"] not in allowed:
                raise ApplyError(FailureReason.MANAGER_UNAVAILABLE, "The manager is unapproved")
        apply_manager(self.config, source, directory / "manager-fallback.compose.yaml")
        self.probe_manager(self.config, self.store, operation.id, claim_id)
        atomic_write(current, source.encode())

    def return_to_source(self, operation_id: UUID) -> None:
        with contextlib.suppress(OwnershipConflict), self.store.claim(operation_id) as owner:
            operation = self.store.get(operation_id)
            if (
                operation.request.kind is not OperationKind.UPDATE
                or operation.stage is not OperationStage.BACKUP
            ):
                return
            try:
                self._return_before_migration(operation)
            except (
                OSError, RuntimeError, ValueError, KeyError, TypeError, subprocess.SubprocessError,
            ) as error:
                reason = error.reason if isinstance(error, ApplyError) else FailureReason.BACKUP
                owner.checkpoint(
                    Checkpoint(operation.stage, CheckpointOutcome.RETRYABLE_ERROR, reason)
                )
            else:
                owner.checkpoint(Checkpoint(OperationStage.CANCELLED, CheckpointOutcome.VERIFIED))

    def _return_before_migration(self, operation: Operation) -> None:
        directory = artifact_directory(self.store, ArtifactKind.STAGING, operation.id)
        plan = strict_json(_artifact(directory / "plan.json"))
        saved = self._source(operation, plan, directory)
        intent = directory / "return-to-source.json"
        committed = canonical_json({"operation": str(operation.id)})
        pending = read_artifact(intent, len(committed))
        if (
            read_artifact(directory / "migration-context.json", LIMIT) is not None
            or pending not in {None, committed}
        ):
            raise ApplyError(
                FailureReason.INCOMPATIBLE_SCHEMA, "Migration may have changed the source database"
            )
        copy = safe_path(self.config["backup"]) / str(operation.id)
        verify_backup = (
            operation.observation.backup_id is not None or copy.exists() or copy.is_symlink()
        )
        data = Path(self.config["data"])
        compose = _artifact(data / "docker-compose.yaml", 8 * COMPOSE_LIMIT)
        prior = strict_json(_artifact(data / CONTROL / "current-release.json"))
        if (
            prior["instance"] != str(operation.instance_id)
            or prior["manifest_digest"] != operation.observation.source_digest
            or prior["revision"] != operation.observation.source_revision
            or prior["compose_digest"] != digest_of(compose)
            or prior["config_digest"] != digest_of(_artifact(data / ".env"))
            or {name: image for name, image in prior["images"].items() if name != "migrate"}
            != saved["source_images"]
        ):
            raise ApplyError(FailureReason.INVALID_PACKAGE, "The working source changed")
        deadline = Deadline(RetryPolicy(), Path(self.config["temporary"]))
        model = _compose_value(strict_json(compose))
        host = ComposeApplicationHost(self.config, directory, model, {
            "services": prior["images"], "profiles": prior["profiles"], "platform": plan["platform"],
            "observed_images": saved["source_images"],
        }, deadline)
        host.bind_images()
        authority = ComposeMaintenanceHost(self.config, operation.id, saved["source_images"])
        pg = authority.validate(saved["containers"], saved["source_revision"])
        context = host.services["gateway"]["environment"].get(CONTEXT_ENV) or None
        if (
            host.migration_locked(pg)
            or host.database_identity(pg) != prior["database"]
            or authority.pgdata != data / saved["layout"]["postgres_data"]
            or (context is None and prior.get("legacy_adopted") is not True)
            or (context is not None and (
                host.phase(pg, context) != "resumed"
                or not host.migration_done(pg, host.containers(), context)
            ))
        ):
            raise ApplyError(FailureReason.INCOMPATIBLE_SCHEMA, "The old deployment is unconfirmed")
        if pending is None:
            write_artifact(intent, committed)
        if host.sql(pg, frozen_sql(operation.id)) == "frozen":
            if verify_backup:
                self._check_copy(operation, saved, pg)
            running = {
                row["Id"] for rows in host.containers().values()
                for row in rows if row["State"]["Running"]
            }
            restart = [
                row["id"] for row in saved["containers"] if row["running"] and row["id"] not in running
            ]
            if restart:
                docker("container", "start", *restart)
            count = sum(
                row["role"] == "task-worker" and row["running"] for row in saved["containers"]
            )
            if not host.wait_for_application(
                pg, context, UUID(prior["operation"]) if context is not None else None,
                self.store.identity().public_url, count,
            ):
                raise ApplyError(FailureReason.GATEWAY_UNAVAILABLE, "The old deployment is not ready")
            host.restore_restart_policy()
        if host.sql(pg, confirm_return_to_source_sql(operation.id)) != "open":
            raise ApplyError(FailureReason.INCOMPATIBLE_SCHEMA, "The old admission remains frozen")

    def execute(self, operation_id: UUID) -> None:
        with contextlib.suppress(OwnershipConflict), self.store.claim(operation_id) as owner:
            operation = self.store.get(operation_id)
            if (
                operation is None
                or operation.stage not in APPLY_STAGES
                or operation.request.kind not in {OperationKind.INSTALL, OperationKind.UPDATE}
            ):
                raise ValueError("This operation cannot deploy an application")
            stage = operation.stage
            reason = FailureReason.INVALID_PACKAGE
            host = None
            pg = None
            try:
                directory = artifact_directory(self.store, ArtifactKind.STAGING, operation_id)
                release, plan, full, env, deadline, historical = self._staged(operation, directory)
                host = ComposeApplicationHost(self.config, directory, full, plan, deadline)
                host.bind_images()
                reason = FailureReason.MANAGER_UNAVAILABLE
                managers = self._manager_images(operation, plan)
                reason = FailureReason.BACKUP
                updating = operation.request.kind is OperationKind.UPDATE
                saved = self._source(operation, plan, directory) if updating else None
                attempt_path = directory / "migration-context.json"
                context = read_artifact(attempt_path, LIMIT)
                if historical and context is None:
                    raise ApplyError(
                        FailureReason.INVALID_PACKAGE, "An expired release cannot start a migration"
                    )
                if stage in {OperationStage.BACKUP, OperationStage.PREPARED}:
                    if stage is OperationStage.BACKUP:
                        if read_artifact(directory / "return-to-source.json", LIMIT) is not None:
                            raise ApplyError(FailureReason.INCOMPATIBLE_SCHEMA, "Return to source is in progress")
                        pg = self._confirm_source(operation, plan, saved)
                    owner.checkpoint(Checkpoint(OperationStage.MIGRATING))
                    stage = OperationStage.MIGRATING

                reason = FailureReason.DATABASE_UNAVAILABLE
                rows = host.containers()
                if not rows.get("postgres"):
                    if updating or context is not None or stage is not OperationStage.MIGRATING:
                        raise ApplyError(
                            FailureReason.DATABASE_UNAVAILABLE, "The expected database is missing"
                        )
                    # Run only PostgreSQL to obtain its identity before writing the immutable
                    # migrator context; PostgreSQL doesn't need the context.
                    write_artifact(
                        directory / "database.compose.yaml", canonical_json(_compose_literal(full))
                    )
                    host.up("postgres", path=directory / "database.compose.yaml")
                if saved is not None and pg is None and context is None:
                    # A reboot after the early journal entry has not authorized touching schema.
                    pg = self._confirm_source(operation, plan, saved)
                pg = pg or host.wait_for_database()

                reason = FailureReason.INCOMPATIBLE_SCHEMA
                marker = canonical_json(
                    {
                        "operation": str(operation_id),
                        "instance": str(operation.instance_id),
                        "manifest": operation.request.release.manifest_digest,
                        "image": plan["services"]["gateway"].split("@")[1],
                        "source": operation.observation.source_revision,
                        "target": operation.observation.target_revision,
                        "database": host.database_identity(pg),
                        "required_extensions": sorted(release.database_schema.required_extensions),
                    }
                )
                write_artifact(attempt_path, marker)
                context_text = marker.decode()
                if historical and (
                    host.phase(pg, context_text) not in {"done", "resumed"}
                    or host.revision(pg) != operation.observation.target_revision
                ):
                    raise ApplyError(
                        FailureReason.INVALID_PACKAGE,
                        "The release expired before a successful migration was confirmed",
                    )

                manager = full["services"]["installation_manager"]
                manager["command"] = ["candidate-web", self.config["data"]]
                manager["healthcheck"] = {
                    "test": [
                        "CMD",
                        "python3",
                        "-c",
                        "import socket; socket.create_connection(('127.0.0.1', 8000), 2).close()",
                    ],
                }
                for role in MANAGED_ROLES:
                    full["services"][role].setdefault("environment", {})[CONTEXT_ENV] = context_text
                compose_bytes = canonical_json(_compose_literal(full))
                env_bytes = _dotenv(env)
                write_artifact(host.path, compose_bytes)
                write_artifact(directory / "configured.env", env_bytes)
                if (
                    updating
                    and host.phase(pg, context_text) != "resumed"
                    and host.sql(pg, frozen_sql(operation_id)) != "frozen"
                ):
                    raise ApplyError(
                        FailureReason.INCOMPATIBLE_SCHEMA, "The update does not own the frozen gate"
                    )

                if stage is OperationStage.MIGRATING:
                    reason = FailureReason.MIGRATION
                    rows = host.containers()
                    if not host.migration_done(pg, rows, context_text):
                        active = any(c["State"]["Running"] for c in rows.get("migrate", ()))
                        migration = classify_migration(
                            phase=host.phase(pg, context_text),
                            revision=host.revision(pg),
                            source=operation.observation.source_revision,
                            target=operation.observation.target_revision,
                            running=active,
                            locked=not active and host.migration_locked(pg),
                        )
                        self._support(host, directory, migration)
                        if migration is MigrationState.UNKNOWN:
                            raise ApplyError(
                                FailureReason.INCOMPATIBLE_SCHEMA,
                                "The live schema has no supported resume checkpoint",
                            )
                        if migration is not MigrationState.IN_PROGRESS:
                            if saved is not None and migration in {
                                MigrationState.NOT_STARTED, MigrationState.CORE_COMMITTED,
                            }:
                                self._check_copy(operation, saved, pg)
                            if not host.up("migrate"):
                                logger.warning(
                                    "Compose did not confirm startup of the one-shot migrator"
                                )
                        host.wait_for_migration(pg, context_text)
                    self._support(host, directory, MigrationState.TARGET_CONFIRMED)
                    owner.checkpoint(
                        Checkpoint(
                            OperationStage.APPLYING,
                            CheckpointOutcome.VERIFIED,
                            observation=Observation(
                                observed_revision=operation.observation.target_revision
                            ),
                        )
                    )
                    stage = OperationStage.APPLYING

                reason = FailureReason.COMPOSE
                origin = self.store.identity().public_url
                workers = int(env["DVT_TASK_WORKERS_COUNT"])
                if stage in {
                    OperationStage.APPLYING,
                    OperationStage.VERIFYING,
                    OperationStage.RESUMING,
                }:
                    host.retire_stopped_services()
                    if (
                        not host.app_ready(pg, context_text, operation_id, origin, workers)
                        and not host.up()
                    ):
                        logger.warning(
                            "Compose did not confirm startup; checking actual service readiness"
                        )
                    if stage is OperationStage.APPLYING:
                        owner.checkpoint(Checkpoint(OperationStage.VERIFYING))
                        stage = OperationStage.VERIFYING
                    self._support(host, directory, MigrationState.TARGET_CONFIRMED)
                    reason = FailureReason.MANAGER_UNAVAILABLE
                    self._apply_manager_health(host, directory, managers, operation, owner)
                    reason = FailureReason.PROFILE_UNHEALTHY
                    if not host.wait_for_application(
                        pg, context_text, operation_id, origin, workers
                    ):
                        raise ApplyError(reason, "The enabled application did not pass readiness")

                reason = FailureReason.COMPOSE
                host.restore_restart_policy()
                data = Path(self.config["data"])
                # Compose runs from the private staging copy until readiness. The previous
                # working pair remains available in its staging directory and verified backup.
                atomic_write(data / ".env", env_bytes)
                atomic_write(data / "docker-compose.yaml", compose_bytes)
                atomic_write(
                    data / CONTROL / "current-release.json",
                    canonical_json(
                        {
                            "format_version": 1,
                            "operation": str(operation_id),
                            "instance": str(operation.instance_id),
                            "version": release.version,
                            "release_id": release.release_id,
                            "manifest_digest": operation.request.release.manifest_digest,
                            "revision": operation.observation.target_revision,
                            "database": host.database_identity(pg),
                            "compose_digest": digest_of(compose_bytes),
                            "config_digest": digest_of(env_bytes),
                            "profiles": plan["profiles"],
                            "images": plan["services"],
                        }
                    ),
                )
                if stage is OperationStage.VERIFYING:
                    owner.checkpoint(
                        Checkpoint(OperationStage.RESUMING, CheckpointOutcome.VERIFIED)
                    )
                    stage = OperationStage.RESUMING
                reason = FailureReason.DATABASE_UNAVAILABLE
                if not host.resume(pg, context_text):
                    raise ApplyError(reason, "The database did not confirm task admission resumed")
                self._support(host, directory, MigrationState.RESUMED)
                owner.checkpoint(
                    Checkpoint(
                        OperationStage.SUCCEEDED,
                        CheckpointOutcome.VERIFIED,
                        observation=Observation(
                            observed_digest=plan["services"]["gateway"].split("@")[1]
                        ),
                    )
                )
            except (
                ApplyError,
                OSError,
                RuntimeError,
                ValueError,
                KeyError,
                TypeError,
                AttributeError,
                subprocess.SubprocessError,
                sqlite3.Error,
            ) as error:
                if isinstance(error, (ApplyError, StagingError)):
                    reason = error.reason
                revision = None
                if stage is OperationStage.MIGRATING and host is not None and pg is not None:
                    with contextlib.suppress(
                        ApplyError, OSError, RuntimeError, subprocess.SubprocessError
                    ):
                        revision = host.revision(pg)
                outcome = (
                    CheckpointOutcome.BLOCKED
                    if reason in {FailureReason.INVALID_PACKAGE, FailureReason.INCOMPATIBLE_SCHEMA}
                    else CheckpointOutcome.RETRYABLE_ERROR
                )
                owner.checkpoint(
                    Checkpoint(
                        stage,
                        outcome,
                        reason,
                        observation=Observation(observed_revision=revision),
                    )
                )
                # Never print command output or protected staging contents.
                logger.warning("Application operation paused at %s: %s", stage.value, reason.value)
