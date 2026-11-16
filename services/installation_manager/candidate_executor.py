"""The detached executor for the isolated manager-only handoff candidate."""

from __future__ import annotations

import contextlib
import json
import subprocess
import time
import urllib.request
from pathlib import Path
from uuid import UUID

from .application.maintenance_backup import MAINTENANCE_STAGES, MaintenanceBackup
from .candidate_auth import CandidateAuth
from .domain.operation_state import (
    ArtifactKind,
    Checkpoint,
    CheckpointOutcome,
    FailureReason,
    Observation,
    OperationKind,
    OperationStage,
    OwnershipConflict,
    ReleasePin,
)
from .domain.release_manifest import Environment, canonical_json
from .host_bootstrap import (
    CONTROL,
    apply_manager,
    atomic_write,
    candidate,
    check_image,
    docker,
    init_container,
)
from .infrastructure.operation_store import FORMAT_VERSION, OperationStore
from .infrastructure.staging_artifacts import artifact_directory, read_artifact, write_artifact
from .infrastructure.staging_commands import Deadline, RetryPolicy
from .infrastructure.staging_host import (
    HostPaths,
    check_filesystems,
    check_platform,
    storage_budgets,
)

CHECK_ERRORS = (OSError, RuntimeError, ValueError, subprocess.SubprocessError)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, _req, _fp, _code, _msg, _headers, _newurl):
        return None


def _project_manager(config: dict, image_ids: dict[str, str]) -> dict | None:
    listed = docker(
        "container",
        "ls",
        "--all",
        "--quiet",
        "--filter",
        f"label=com.docker.compose.project={config['project']}",
    ).stdout.split()
    if not listed:
        return None
    if len(listed) != 1:
        raise ValueError("The candidate project must contain only the installation manager")
    (manager,) = json.loads(docker("container", "inspect", listed[0]).stdout)
    image = manager["Config"]["Image"]
    ports = manager["HostConfig"]["PortBindings"]
    mounts = {(m["Type"], m["Source"], m["Destination"]) for m in manager["Mounts"]}
    data = config["data"]
    if (
        manager["Config"]["Labels"].get("com.docker.compose.service") != "installation_manager"
        or image_ids.get(image) != manager["Image"]
        or ports != {"8000/tcp": [{"HostIp": config["address"], "HostPort": str(config["port"])}]}
        or mounts
        != {
            ("bind", data, data),
            ("bind", "/var/run/docker.sock", "/var/run/docker.sock"),
        }
    ):
        raise ValueError(
            "The manager image, service, ports or mounts disagree with the approved project"
        )
    return manager


def _check_host(config: dict, staging: Path) -> None:
    paths = HostPaths(
        temporary=Path(config["temporary"]),
        backup=Path(config["backup"]),
        containerd_root=Path(config["containerd_root"]) if config["containerd_root"] else None,
        os_release=Path("/run/dvt-host-os"),
    )
    env = Environment.model_validate(
        {
            "distributions": {"debian": ["13"], "ubuntu": ["24.04"]},
            "min_docker": "28.0.0",
            "min_compose": "2.24.0",
            "pull_parallelism": 1,
            "base": {
                "min_cpus": 1,
                "min_ram_bytes": 1024**3,
                "docker_reserve_bytes": 1024**2,
                "data_reserve_bytes": 1024**2,
                "temporary_bytes": 1024**2,
                "reserve_inodes": 16,
                "max_task_workers": 1,
            },
            "profiles": {},
        }
    )
    info = json.loads(docker("info", "--format", "{{json .}}").stdout)
    if info["DockerRootDir"] != config["docker_root"]:
        raise ValueError("Docker data root changed")
    check_platform(
        info,
        docker("compose", "version", "--short").stdout.strip(),
        paths.os_release,
        env,
        env.base,
    )
    check_filesystems(
        storage_budgets(
            info,
            paths,
            Path(config["data"]),
            staging,
            env.base,
            [],
            1,
            set(),
            Deadline(RetryPolicy(), paths.temporary),
        )
    )


def _probe(config: dict, store: OperationStore, operation_id: UUID, claim_id: UUID) -> None:
    auth = CandidateAuth(config)
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        urllib.request.HTTPSHandler(context=auth.probe_tls()),
        _NoRedirect(),
    )
    request = urllib.request.Request(
        f"{auth.origin}/api/operations/{operation_id}",
        headers={"Authorization": f"Bearer {auth.machine}"},
    )
    deadline = time.monotonic() + 70
    while time.monotonic() < deadline:
        try:
            with opener.open(request, timeout=3) as response:
                data = json.load(response)
            if (
                data["journal_format"] == FORMAT_VERSION
                and data["operation"]["id"] == str(operation_id)
                and data["operation"]["instance_id"] == str(store.identity().instance_id)
                and data["operation"]["last_owner"]["claim_id"] == str(claim_id)
            ):
                return
        except (OSError, KeyError, TypeError, ValueError):
            pass
        time.sleep(1)
    raise RuntimeError("The manager did not confirm access to the current journal")


def execute(config: dict, store: OperationStore, operation_id: UUID) -> None:
    operation = store.get(operation_id)
    if operation is not None and operation.request.kind is OperationKind.UPDATE:
        if operation.stage in MAINTENANCE_STAGES:
            MaintenanceBackup(store, config).execute(operation_id)
        return
    with contextlib.suppress(OwnershipConflict), store.claim(operation_id) as owner:
        operation = store.get(operation_id)
        if (
            operation.instance_id != UUID(config["instance"])
            or operation.request.kind is not OperationKind.MANAGER_RECOVERY
            or operation.request.release != ReleasePin(*candidate(config))
        ):
            raise ValueError("The operation does not refer to the approved handoff")
        directory = artifact_directory(store, ArtifactKind.STAGING, operation_id)
        old, target = config["manager"], config["candidate"]
        outcome = CheckpointOutcome.VERIFIED
        failed = CheckpointOutcome.BLOCKED
        reason = FailureReason.MANAGER_UNAVAILABLE
        stage = operation.stage
        if stage is OperationStage.ADMITTED:
            stage = owner.checkpoint(Checkpoint(OperationStage.PREPARING)).stage

        try:
            image_ids = {image: check_image(image) for image in (old, target)}
            _check_host(config, directory)
            manager = _project_manager(config, image_ids)
            if stage in {OperationStage.PREPARING, OperationStage.PREPARED}:
                if not manager or not manager["State"]["Running"]:
                    raise ValueError("The running manager disappeared before handoff")
                for image in (old, target):
                    reply = init_container({**config, "manager": image}, "candidate-inspect")
                    if reply != str(FORMAT_VERSION):
                        raise ValueError("A manager cannot read the installed journal format")
                write_artifact(
                    directory / "handoff.json",
                    canonical_json(
                        {
                            "format_version": 1,
                            "journal_format": FORMAT_VERSION,
                            "operation_id": str(operation_id),
                            "instance_id": config["instance"],
                            "source_image": old,
                            "target_image": target,
                            "executor_image": config["executor"],
                            "origin": f"https://localhost:{config['port']}",
                        }
                    ),
                )
                owner.checkpoint(
                    Checkpoint(
                        OperationStage.PREPARED,
                        outcome,
                        observation=Observation(
                            source_digest=old.split("@")[1],
                            target_digest=target.split("@")[1],
                            staging_id=operation_id,
                        ),
                    )
                )
                stage = OperationStage.PREPARED
        except CHECK_ERRORS:
            if stage in {OperationStage.PREPARING, OperationStage.PREPARED}:
                owner.checkpoint(Checkpoint(OperationStage.FAILED, failed, reason))
            else:
                owner.checkpoint(Checkpoint(stage, failed, reason))
            return

        if stage in {OperationStage.PREPARED, OperationStage.RECOVERY_REQUIRED}:
            stage = owner.checkpoint(Checkpoint(OperationStage.RECOVERING)).stage
        if stage not in {OperationStage.RECOVERING, OperationStage.RESUMING}:
            raise ValueError("Unexpected candidate operation stage")

        def reconcile(image: str) -> None:
            current = _project_manager(config, image_ids)
            if (
                not current
                or not current["State"]["Running"]
                or current["Image"] != image_ids[image]
            ):
                apply_manager(config, image, directory / "handoff.compose.yaml")
            current = _project_manager(config, image_ids)
            if (
                not current
                or not current["State"]["Running"]
                or current["Image"] != image_ids[image]
            ):
                raise RuntimeError("Docker did not start the expected manager")
            _probe(config, store, operation_id, owner.record.claim_id)
            atomic_write(Path(config["data"]) / CONTROL / "current-manager", image.encode())

        fallback_path = directory / "manager-fallback.json"
        fallback_intent = canonical_json({"image": old, "reason": reason})
        fallback = read_artifact(fallback_path, len(fallback_intent))
        if fallback is not None and fallback != fallback_intent:
            raise ValueError("The recorded manager fallback disagrees with the approved source")
        if fallback is None:
            try:
                reconcile(target)
            except CHECK_ERRORS:
                # A reboot during the fallback must keep recovering the source manager.
                write_artifact(fallback_path, fallback_intent)
                fallback = fallback_intent
        if fallback is not None:
            if stage is OperationStage.RESUMING:
                owner.checkpoint(Checkpoint(OperationStage.RECOVERY_REQUIRED, failed, reason))
                owner.checkpoint(Checkpoint(OperationStage.RECOVERING))
            owner.checkpoint(Checkpoint(OperationStage.RECOVERING, failed, reason))
            try:
                reconcile(old)
            except CHECK_ERRORS:
                owner.checkpoint(Checkpoint(OperationStage.RECOVERY_REQUIRED, failed, reason))
            else:
                owner.checkpoint(
                    Checkpoint(
                        OperationStage.CANCELLED,
                        outcome,
                        observation=Observation(observed_digest=old.split("@")[1]),
                    )
                )
            return

        if stage is OperationStage.RECOVERING:
            owner.checkpoint(Checkpoint(OperationStage.RESUMING, outcome))
        owner.checkpoint(
            Checkpoint(
                OperationStage.SUCCEEDED,
                outcome,
                observation=Observation(observed_digest=target.split("@")[1]),
            )
        )
