"""The detached executor for candidate deployments and manager handoff."""

from __future__ import annotations

import contextlib
import http.client
import ipaddress
import json
import socket
import ssl
import subprocess
import time
from pathlib import Path
from uuid import UUID

from .application.application_apply import APPLY_STAGES, ApplicationApply
from .application.legacy_adopt import PLAN as LEGACY_ADOPTION, execute as adopt_legacy
from .application.maintenance_backup import MAINTENANCE_STAGES, MaintenanceBackup
from .application.online_operations import is_online, prepare_online
from .application.restore_runtime import AUTHORIZATION, RestoreRuntime
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


class _ManagerConnection(http.client.HTTPSConnection):
    def __init__(self, address: str, port: int, context: ssl.SSLContext) -> None:
        self.address = ipaddress.ip_address(address)
        if not self.address.is_loopback:
            raise ValueError("The protected manager probe requires a loopback IP address")
        self.tls_context = context
        super().__init__("localhost", port, timeout=3, context=context)

    def connect(self) -> None:
        family = socket.AF_INET6 if self.address.version == 6 else socket.AF_INET
        connection = socket.socket(family, socket.SOCK_STREAM)
        try:
            connection.settimeout(self.timeout)
            connection.connect((str(self.address), self.port))
            # The transport is numeric. The certificate and HTTP endpoint still
            # use the manager's established localhost identity.
            self.sock = self.tls_context.wrap_socket(connection, server_hostname=self.host)
        except BaseException:
            connection.close()
            raise


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
    tls = auth.probe_tls()
    headers = {"Host": auth.host, "Authorization": f"Bearer {auth.machine}"}
    path = f"/api/operations/{operation_id}"
    response_limit = 256 * 1024
    deadline = time.monotonic() + 70
    while time.monotonic() < deadline:
        try:
            connection = _ManagerConnection(config["address"], config["port"], tls)
            with contextlib.closing(connection):
                connection.request("GET", path, headers=headers)
                with connection.getresponse() as response:
                    raw = response.read(response_limit + 1) if response.status == 200 else b""
            if 0 < len(raw) <= response_limit:
                data = json.loads(raw)
                if (
                    data["journal_format"] == FORMAT_VERSION
                    and data["operation"]["id"] == str(operation_id)
                    and data["operation"]["instance_id"] == str(store.identity().instance_id)
                    and data["operation"]["last_owner"]["claim_id"] == str(claim_id)
                ):
                    return
        except (OSError, http.client.HTTPException, KeyError, TypeError, ValueError):
            pass
        time.sleep(1)
    raise RuntimeError("The manager did not confirm access to the current journal")


def _execute_application(config: dict, store: OperationStore, operation) -> None:
    operation_id = operation.id
    if operation.stage in {OperationStage.ADMITTED, OperationStage.PREPARING}:
        if not is_online(store, operation) or not prepare_online(config, store, operation):
            return
        operation = store.get(operation.id)
    directory = store.artifact_path(ArtifactKind.STAGING, operation_id)
    if (directory / "restored-data.json").exists():
        if (directory / AUTHORIZATION).exists():
            RestoreRuntime(store, config, _probe).execute(operation_id)
        return
    if operation.stage is OperationStage.BACKUP and (directory / "return-to-source.json").exists():
        ApplicationApply(store, config, _probe).return_to_source(operation_id)
        return
    if (
        operation.request.kind is OperationKind.UPDATE
        and operation.stage in MAINTENANCE_STAGES
        and operation.observation.backup_id is None
    ):
        MaintenanceBackup(store, config).execute(operation_id)
        operation = store.get(operation_id)
    if operation.stage in APPLY_STAGES and (
        operation.request.kind is OperationKind.INSTALL
        or operation.observation.backup_id == operation_id
    ):
        ApplicationApply(store, config, _probe).execute(operation_id)


def execute(config: dict, store: OperationStore, operation_id: UUID) -> None:
    operation = store.get(operation_id)
    if operation is None:
        raise ValueError("Unknown candidate operation")
    if operation.stage.terminal:
        return
    if operation.request.kind in {OperationKind.INSTALL, OperationKind.UPDATE}:
        _execute_application(config, store, operation)
        return
    if (store.artifact_path(ArtifactKind.STAGING, operation_id) / LEGACY_ADOPTION).exists():
        adopt_legacy(config, store, operation_id, _probe)
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
