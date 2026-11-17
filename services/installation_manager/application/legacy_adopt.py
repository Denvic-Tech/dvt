"""Opt in a legacy bootstrap running a verified, admission-capable DVT release."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID

from ..domain.operation_state import (
    ArtifactKind,
    Checkpoint,
    CheckpointOutcome,
    FailureReason,
    InstanceIdentity,
    Observation,
    OperationKind,
    OperationRequest,
    OperationStage,
    OwnershipConflict,
    ReleasePin,
)
from ..domain.release_manifest import canonical_json, digest_of, strict_json
from ..host_bootstrap import (
    CONTROL,
    atomic_write,
    check_image,
    docker,
    image_store,
    init_container,
    install_unit,
    load_host,
    manager_compose,
    safe_path,
)
from ..infrastructure.application_host import CONTEXT_ENV, DATABASE_ID, MANAGED_ROLES
from ..infrastructure.maintenance_host import ComposeMaintenanceHost
from ..infrastructure.operation_files import sync_directory
from ..infrastructure.operation_store import FORMAT_VERSION, OperationStore
from ..infrastructure.release_verification import MAX_MANIFEST_BYTES, TrustPolicy, verify_file
from ..infrastructure.staging_artifacts import artifact_directory, write_artifact
from ..infrastructure.staging_compose import COMPOSE_LIMIT
from ..infrastructure.staging_docker import _compose_value, image_references
from .application_apply import LIMIT, _artifact, _compose_literal, _validate_runtime
from .legacy_transition import LegacyPolicy, _read, observe

PLAN = "legacy-adoption.json"


def _containers(project: str) -> dict[str, list[dict]]:
    ids = docker(
        "container", "ls", "--all", "--quiet", "--no-trunc", "--filter",
        f"label=com.docker.compose.project={project}",
    ).stdout.split()
    containers = json.loads(docker("container", "inspect", *ids).stdout) if ids else []
    roles: dict[str, list[dict]] = {}
    for container in containers:
        labels = container["Config"]["Labels"]
        if (
            labels["com.docker.compose.project"] != project
            or labels["com.docker.compose.oneoff"].lower() != "false"
        ):
            raise ValueError("The Compose scope changed")
        role = labels["com.docker.compose.service"]
        roles.setdefault(role, []).append(container)
    return roles


def _host_config(data: Path, values: dict, source: dict) -> InstanceIdentity:
    identifier = UUID(_read(data / "installation" / "instance_id", 128).decode().strip())
    if (
        values["version"] != 1
        or values["data"] != str(data)
        or values["project"] != source["project"]
        or values["instance"] != str(identifier)
        or values["address"] != "127.0.0.1"
    ):
        raise ValueError("The legacy installation identity and host settings differ")
    identity = InstanceIdentity(
        identifier, str(data), values["project"], values["address"], values["port"],
        values["public_url"],
    )
    [binding] = source["services"]["installation_manager"]["bindings"]
    if binding != {"address": identity.manager_address, "port": identity.manager_port,
                   "protocol": "tcp", "target": 8000}:
        raise ValueError("The protected manager would change the legacy bind")
    for image in {values["manager"], values["candidate"], values["executor"]}:
        check_image(image)
    if values["manager"] == values["candidate"]:
        raise ValueError("Select a distinct manager candidate for future handoffs")
    info = json.loads(docker("info", "--format", "{{json .}}").stdout)
    root = safe_path(values["docker_root"])
    containerd = safe_path(values["containerd_root"]) if values["containerd_root"] else None
    temporary, backup = [safe_path(values[key]) for key in ("temporary", "backup")]
    if (
        str(root) != info["DockerRootDir"]
        or image_store(info) != bool(containerd)
        or len({temporary, backup, data}) != 3
        or any(data.is_relative_to(path) for path in (temporary, backup))
        or any(
            path.is_relative_to(backing) or backing.is_relative_to(path)
            for path in (data, temporary, backup)
            for backing in (root, containerd) if backing is not None
        )
    ):
        raise ValueError("The compatibility bridge would change or overlap backing storage")
    return identity


def _control(data: Path, config: dict, tls: Path) -> None:
    control = data / CONTROL
    if control.exists():
        if load_host(data) != config:
            raise ValueError("A different protected bootstrap already owns the instance")
        return
    with TemporaryDirectory(prefix=".legacy-bootstrap-", dir=data) as temporary:
        directory = Path(temporary)
        for name in ("cert.pem", "key.pem", "ca.pem"):
            atomic_write(directory / name, _read(tls / name, 64 * 1024))
        atomic_write(directory / "host.json", canonical_json(config))
        atomic_write(directory / "current-manager", config["manager"].encode())
        directory.rename(control)
        sync_directory(data)


def _prepare(data, project, config, tls, policy, source, target, pin):
    report = observe(data, project, policy, target=target)
    if report["blockers"] or report["observed_version"] != source.version:
        raise ValueError("The source requires a different, verified legacy bridge")
    identity = _host_config(data, config, report)
    distribution = source.platforms["linux/amd64"]
    template = _read(data / "docker-compose.yaml", COMPOSE_LIMIT)
    verify_file(template, distribution.compose, "legacy Compose")
    profiles = ["ai-mcp"] if "dvt-ai-mcp" in report["services"] else []
    model = _compose_value(json.loads(docker(
        "compose", "--project-name", project, "--project-directory", str(data),
        "--env-file", str(data / ".env"), "--file", str(data / "docker-compose.yaml"),
        "--profile", "*", "config", "--format", "json",
    ).stdout))
    if report["observed_revision"] != source.database_schema.target_revision:
        raise ValueError("The signed legacy release does not support the observed revision")
    images = {
        role: distribution.images[role].reference for role in report["services"]
    }
    if (
        any(report["observed_images"][role] != ref.rsplit("@", 1)[-1] for role, ref in images.items())
        or set(distribution.images) != set(model["services"])
        or any(model["services"][role]["image"] != entry.reference
               for role, entry in distribution.images.items())
        or any(model["services"][role]["environment"].get(CONTEXT_ENV)
               for role in MANAGED_ROLES)
    ):
        raise ValueError("The observed images and legacy Compose deployment differ")
    images["migrate"] = distribution.images["migrate"].reference
    _validate_runtime({"services": {role: model["services"][role] for role in images}})
    roles = _containers(project)
    [gateway] = roles["gateway"]
    live_env = dict(item.split("=", 1) for item in gateway["Config"]["Env"] if "=" in item)
    live_origin = live_env["GATEWAY_ORIGINS"].split(";", 1)[0]
    if live_origin.rstrip("/") != identity.public_url:
        raise ValueError("The protected identity would change the legacy public origin")
    manager = model["services"]["installation_manager"]
    fallback = {"name": project, "services": {"installation_manager": manager},
                "networks": model["networks"]}
    # The application stays running. The manager's data root is remapped within its
    # container so the bootstrap reader can see the very same durable host bind.
    model["services"]["installation_manager"] = manager_compose(config, config["manager"])[
        "services"
    ]["installation_manager"]
    images["installation_manager"] = config["manager"]
    source_data = {
        "format_version": 1,
        "instance": str(identity.instance_id),
        "version": source.version,
        "release_id": pin.release_id,
        "manifest_digest": pin.manifest_digest,
        "revision": report["observed_revision"],
        "profiles": profiles,
        "images": images,
        "legacy_adopted": True,
        "required_extensions": source.database_schema.required_extensions,
    }
    pg = _verify_roles(roles, images, source_data["revision"], manager=manager["image"])
    env = _read(data / ".env", LIMIT)
    _control(data, config, tls)
    if init_container(config, "candidate-init"):
        raise ValueError("Unexpected protected bootstrap response")
    store = OperationStore.for_host(data)
    if store.identity() != identity:
        raise ValueError("The protected journal belongs to another installation")
    operation = store.admit(
        OperationRequest(OperationKind.MANAGER_RECOVERY, pin),
        idempotency_key="legacy-adopt:" + pin.manifest_digest,
    )
    with store.claim(operation.id) as owner:
        directory = artifact_directory(store, ArtifactKind.STAGING, operation.id)
        write_artifact(directory / "legacy-fallback.compose.yaml", canonical_json(_compose_literal(fallback)))
        compose = canonical_json(_compose_literal(model))
        write_artifact(directory / "legacy-working.compose.yaml", compose)
        write_artifact(directory / "legacy-env", env)
        write_artifact(directory / PLAN, canonical_json({
            "fallback": manager["image"],
            "source": {
                **source_data,
                "operation": str(operation.id),
                "database": ComposeMaintenanceHost.sql(pg, DATABASE_ID),
                "compose_digest": digest_of(compose),
                "config_digest": digest_of(env),
            },
            "containers": _application_containers(roles),
        }))
        if operation.stage is OperationStage.ADMITTED:
            owner.checkpoint(Checkpoint(OperationStage.PREPARING))
    return store, operation.id


def _application_containers(roles) -> dict[str, list[str]]:
    return {
        role: sorted(container["Id"] for container in rows)
        for role, rows in roles.items() if role != "installation_manager"
    }


def _verify_roles(roles, expected, revision, *, manager) -> str:
    expected_roles = set(expected)
    if manager is None:
        expected_roles.discard("installation_manager")
    if set(roles) != expected_roles:
        raise ValueError("Unexpected Compose roles in the legacy release")
    for role, group in roles.items():
        if not group or (len(group) != 1 and role != "task-worker"):
            raise ValueError("Unexpected legacy replicas")
        for container in group:
            reference = manager if role == "installation_manager" else expected[role]
            (image,) = json.loads(docker("image", "inspect", container["Image"]).stdout)
            state = container["State"]
            if reference not in image_references(image) or (
                role == "migrate"
                and not (state["Status"] == "exited" and state["ExitCode"] == 0)
            ) or (role not in {"installation_manager", "migrate"} and not state["Running"]):
                raise ValueError("The observed legacy role differs from the verified source")
    (pg,) = roles["postgres"]
    pgid = pg["Id"]
    if (
        ComposeMaintenanceHost.sql(pgid, "SELECT version_num FROM alembic_version") != revision
        or ComposeMaintenanceHost.sql(
            pgid, "SELECT 'open' FROM task_admission_control "
                  "WHERE singleton = 1 AND operation_id IS NULL AND NOT frozen",
        ) != "open"
    ):
        raise ValueError("The legacy application has no confirmed compatible admission guard")
    return pgid


def execute(config, store, operation_id, probe) -> bool:
    with contextlib.suppress(OwnershipConflict), store.claim(operation_id) as owner:
        operation = store.get(operation_id)
        directory = artifact_directory(store, ArtifactKind.STAGING, operation_id)
        stage = operation.stage
        if stage.terminal:
            return stage is OperationStage.SUCCEEDED
        data = Path(config["data"])
        reason = FailureReason.INCOMPATIBLE_RELEASE
        try:
            plan = strict_json(_artifact(directory / PLAN))
            source = plan["source"]
            if (
                operation.request.kind is not OperationKind.MANAGER_RECOVERY
                or source["instance"] != str(operation.instance_id)
                or source["instance"] != config["instance"]
                or store.identity().compose_project != config["project"]
                or source["operation"] != str(operation.id)
                or source["manifest_digest"] != operation.request.release.manifest_digest
                or source["images"]["installation_manager"] != config["manager"]
            ):
                raise ValueError("The legacy adoption does not belong to this host")
            working = _artifact(directory / "legacy-working.compose.yaml", 8 * COMPOSE_LIMIT)
            env = _artifact(directory / "legacy-env")
            if digest_of(working) != source["compose_digest"] or digest_of(env) != source["config_digest"]:
                raise ValueError("The legacy recovery instructions changed")

            roles = _containers(config["project"])
            if _application_containers(roles) != plan["containers"]:
                raise ValueError("The running application changed after the legacy plan")
            managers = roles.get("installation_manager", ())
            if len(managers) > 1:
                raise ValueError("Multiple legacy managers own this project")
            running = managers[0] if managers else None
            old_id = check_image(plan["fallback"])
            bridge_id = check_image(config["manager"])
            manager = None
            if running is not None:
                references = {old_id: plan["fallback"], bridge_id: config["manager"]}
                manager = references.get(running["Image"])
                if manager is None:
                    raise ValueError("An unverified manager owns the saved bind")
            elif stage not in {OperationStage.RECOVERING, OperationStage.RESUMING}:
                raise ValueError("The expected legacy manager disappeared before handoff")
            pgid = _verify_roles(roles, source["images"], source["revision"], manager=manager)
            if ComposeMaintenanceHost.sql(pgid, DATABASE_ID) != source["database"]:
                raise ValueError("The legacy database belongs to another installation")
            if stage is OperationStage.ADMITTED:
                owner.checkpoint(Checkpoint(OperationStage.PREPARING))
                stage = OperationStage.PREPARING
            if stage is OperationStage.PREPARING:
                if init_container(config, "candidate-inspect") != str(FORMAT_VERSION):
                    raise ValueError("The compatible manager cannot read the journal")
                owner.checkpoint(Checkpoint(
                    OperationStage.PREPARED, CheckpointOutcome.VERIFIED,
                    observation=Observation(
                        source_digest=source["manifest_digest"], source_revision=source["revision"],
                        observed_digest=source["images"]["gateway"].rsplit("@", 1)[-1],
                        observed_revision=source["revision"], staging_id=operation.id,
                    ),
                ))
                stage = OperationStage.PREPARED
            if stage is OperationStage.PREPARED:
                owner.checkpoint(Checkpoint(OperationStage.RECOVERING))
                stage = OperationStage.RECOVERING
            reason = FailureReason.MANAGER_UNAVAILABLE
            try:
                if (
                    running is None or running["Image"] != bridge_id
                    or not running["State"]["Running"]
                    or running["Config"]["Cmd"] != ["candidate-web", config["data"]]
                ):
                    _run_manager(config, directory / "legacy-working.compose.yaml")
                probe(config, store, operation_id, owner.record.claim_id)
                if _application_containers(_containers(config["project"])) != plan["containers"]:
                    raise ValueError("The legacy application changed during manager replacement")
            except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
                _run_manager(config, directory / "legacy-fallback.compose.yaml")
                raise
            if stage is OperationStage.RECOVERING:
                owner.checkpoint(Checkpoint(OperationStage.RESUMING, CheckpointOutcome.VERIFIED))
                stage = OperationStage.RESUMING
            atomic_write(data / "docker-compose.yaml", working)
            atomic_write(data / ".env", env)
            atomic_write(data / CONTROL / "current-release.json", canonical_json(source))
            owner.checkpoint(Checkpoint(OperationStage.SUCCEEDED, CheckpointOutcome.VERIFIED))
        except (OSError, ValueError, RuntimeError, TypeError, KeyError, subprocess.SubprocessError):
            owner.checkpoint(Checkpoint(stage, CheckpointOutcome.RETRYABLE_ERROR, reason))
        else:
            return True
    return False


def _run_manager(config, compose):
    docker(
        "compose", "--project-name", config["project"], "--project-directory", config["data"],
        "--env-file", "/dev/null", "--file", str(compose),
        "up", "--detach", "--no-deps", "--pull", "never", "--no-build",
        "installation_manager",
    )


def main() -> int:
    from ..candidate_executor import _probe

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", required=True, type=Path)
    parser.add_argument("--bootstrap-config", type=Path)
    parser.add_argument("--tls-dir", type=Path)
    parser.add_argument("--predecessors", type=Path)
    parser.add_argument("--trust", type=Path)
    for name in ("source", "target"):
        parser.add_argument(f"--{name}-manifest", type=Path)
        parser.add_argument(f"--{name}-digest")
        parser.add_argument(f"--{name}-release")
    parser.add_argument("--resume", type=UUID)
    args = parser.parse_args()
    result = False
    try:
        if os.geteuid():
            raise ValueError("Root is required to adopt a legacy manager")
        data = safe_path(args.dir)
        if args.resume:
            config = load_host(data)
            store, operation = OperationStore.for_host(data), args.resume
        else:
            trust = TrustPolicy.from_document(strict_json(_read(args.trust, LIMIT)))
            source_pin = ReleasePin(args.source_release, args.source_digest)
            source = trust.verify(_read(args.source_manifest, MAX_MANIFEST_BYTES), source_pin)
            target = trust.verify(
                _read(args.target_manifest, MAX_MANIFEST_BYTES),
                ReleasePin(args.target_release, args.target_digest),
            )
            config = strict_json(_read(args.bootstrap_config, LIMIT))
            policy = LegacyPolicy.model_validate_json(_read(args.predecessors, LIMIT))
            store, operation = _prepare(
                data, config["project"], config, args.tls_dir, policy, source, target, source_pin,
            )
        result = execute(config, store, operation, _probe)
        if result:
            for key in ("backup", "temporary"):
                safe_path(config[key]).mkdir(mode=0o700, parents=True, exist_ok=True)
            install_unit(data, config)
            sys.stdout.write(json.dumps({"operation_id": str(operation), "stage": "succeeded"}) + "\n")
    except (OSError, ValueError, RuntimeError, TypeError, KeyError, subprocess.SubprocessError):
        pass
    if not result:
        sys.stderr.write("Legacy adoption paused. Review the verified plan and operation journal.\n")
    return 0 if result else 1


if __name__ == "__main__":
    sys.exit(main())
