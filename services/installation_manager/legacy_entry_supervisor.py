"""Supervise an admitted legacy job across interruptions without owning update stages."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from .application.legacy_import import (
    ERRORS,
    PLAN,
    ROLLBACK_STAGES,
    _operation_id,
    return_to_legacy,
)
from .application.legacy_transition import _read
from .domain.operation_state import ArtifactKind, OperationKind, OperationStage
from .domain.release_manifest import canonical_json
from .host_bootstrap import (
    STATE,
    atomic_write,
    container_name,
    docker,
    launch,
    load_host,
    safe_path,
)
from .infrastructure.operation_files import executor_lock
from .infrastructure.operation_store import OperationStore
from .infrastructure.staging_artifacts import read_artifact

STATUS = Path("installation/legacy-entry-status.json")
MAX_STARTS = 3
STOP_STAGES = {
    OperationStage.RECOVERY_REQUIRED,
    OperationStage.RECOVERING,
}


def initial_install_id(project: str, job_id: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"DVT/{project}/legacy-install:{job_id}")


def _update_command(data: Path, marker: dict, image: str, package: Path) -> None:
    subprocess.run(
        [
            sys.executable, "-m", "services.installation_manager.application.legacy_import",
            "--dir", str(data), "--project", marker["project"],
            "--version", marker["target_version"], "--manifest-digest", marker["manifest_digest"],
            "--legacy-job-id", marker["job_id"], "--catalog-config", str(package / "catalog.json"),
            "--executor", image,
        ],
        check=True,
        timeout=600,
    )


def _executor_running(config: dict) -> bool:
    reply = docker(
        "container", "inspect", "--format", "{{.State.Running}}", container_name(config),
        check=False, timeout=15,
    )
    return not reply.returncode and reply.stdout.strip() == "true"


def run(data: Path, marker: dict, image: str, package: Path) -> str:  # noqa: PLR0911
    path = safe_path(data / STATUS)
    raw = read_artifact(path, 4096)
    status = json.loads(raw) if raw is not None else {}
    if status.get("job_id") != marker["job_id"] or status.get("manifest_digest") != marker["manifest_digest"]:
        status = {"job_id": marker["job_id"], "manifest_digest": marker["manifest_digest"], "starts": 0}

    def persist(phase: str) -> str:
        status["phase"] = phase
        atomic_write(path, canonical_json(status))
        return phase

    if status.get("phase") in {"succeeded", "restored", "cancelled", "failed", "operator_required"}:
        return status["phase"]

    installation = marker["kind"] == "install"
    if installation:
        operation_id = initial_install_id(marker["project"], marker["job_id"])
    else:
        instance = UUID(_read(data / "installation" / "instance_id", 128).decode().strip())
        operation_id = _operation_id(marker["job_id"], instance)

    def restore() -> str:
        from .legacy_entry_recovery import restore_before_admission

        persist("restoring")
        try:
            with executor_lock(safe_path(data / ".legacy-import.lock")):
                restore_before_admission(data, marker, image)
        except (OSError, ValueError, RuntimeError, KeyError, TypeError, subprocess.SubprocessError):
            return persist("operator_required")
        return persist("restored")

    if status.get("phase") == "restoring":
        return restore()
    while True:
        state_exists = (data / STATE / "journal.sqlite3").is_file()
        store = OperationStore.for_host(data) if state_exists else None
        operation = store.current_step(operation_id) if store is not None else None
        if operation is not None and operation.stage.terminal:
            if operation.stage is OperationStage.CANCELLED and status.get("phase") == "restoring_admitted":
                return persist("restored")
            if (
                not installation and operation.stage is OperationStage.SUCCEEDED
                and operation.request.release.manifest_digest != marker["manifest_digest"]
            ):
                return persist("operator_required")
            return persist(operation.stage.value)
        if operation is not None and operation.stage in STOP_STAGES:
            return persist("operator_required")
        config = load_host(data) if operation is not None else None
        if config is not None and _executor_running(config):
            if status.get("phase") not in {"running", "restoring_admitted"}:
                persist("running")
            time.sleep(3)
            continue
        step = str(operation.id) if operation is not None else "legacy"
        if status.get("step") != step:
            status.update(step=step, starts=0)
        if status["starts"] >= MAX_STARTS or status.get("phase") == "restoring_admitted":
            if not installation and operation is None and status.get("phase") != "restoring_admitted":
                return restore()
            if (
                not installation and operation is not None and operation.id == operation_id
                and operation.stage in ROLLBACK_STAGES
                and operation.request.kind is OperationKind.UPDATE
            ):
                persist("restoring_admitted")
                try:
                    return_to_legacy(config, store, operation_id, legacy_job=marker)
                except ERRORS:
                    return persist("operator_required")
                return persist("restored")
            return persist("operator_required")
        status["starts"] += 1
        persist("starting")
        try:
            if installation and (operation is None or operation.stage is OperationStage.ADMITTED):
                from .legacy_entry_install import first_install

                first_install(data, image, marker, package)
            elif config is None or (
                operation.id == operation_id and operation.stage is OperationStage.ADMITTED
                and not (store.artifact_path(ArtifactKind.STAGING, operation_id) / PLAN).is_file()
            ):
                _update_command(data, marker, image, package)
            else:
                launch(config, str(operation.id))
        except (OSError, ValueError, RuntimeError, KeyError, TypeError, subprocess.SubprocessError):
            if (
                not installation and operation is None and status["starts"] >= MAX_STARTS
            ):
                return restore()
        time.sleep(5)
