"""Restore the historical application before a managed import owns any changes."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import UUID

from .application.legacy_adopt import _containers
from .application.legacy_import import (
    APPLICATION,
    CORE,
    _backups,
    _old_model,
    _pin_fallback,
    check_historical_migrator,
    legacy_source_version,
)
from .application.legacy_transition import _read, _same_service
from .domain.operation_state import InstanceIdentity
from .domain.release_manifest import canonical_json, digest_of
from .host_bootstrap import CONTROL, STATE, atomic_write, check_image, docker, safe_path
from .infrastructure.maintenance_host import ComposeMaintenanceHost
from .infrastructure.operation_files import sync_directory
from .infrastructure.operation_store import FORMAT_VERSION
from .infrastructure.staging_compose import COMPOSE_LIMIT, _source_service, _target_service
from .legacy_entry import LABEL, _handoff_identity, _is_legacy_manager

# This loader runs inside the original image. It uses the released job store and
# API, including their normal behavior when another update replaces a finished job.
_REPORT_ROLLBACK = """\
import sys
from datetime import datetime
from services.installation_manager.domain.models import Job, JobKind, JobState
from services.installation_manager.main import jobs, main

job = Job(JobKind.UPDATE, [])
job.id, job.version = sys.argv[1:3]
if sys.argv[3]:
    job.started_at = datetime.fromisoformat(sys.argv[3])
description = "Обновление прервано. Исходная версия DVT восстановлена."
job.log(description)
job.finish(JobState.FAILED, description)
job.finished_at = datetime.fromisoformat(sys.argv[4])
jobs.start(job)
main()
"""


def rollback_job(marker: dict) -> dict[str, str]:
    return {
        "job_id": marker["job_id"],
        "requested_version": marker["requested_version"],
        "started_at": marker.get("started_at", ""),
        "finished_at": datetime.now(UTC).isoformat(),
    }


def configure_rollback_manager(model: dict, job: dict) -> None:
    manager = model["services"]["installation_manager"]
    manager["entrypoint"] = ["python3"]
    manager["command"] = [
        "-c", _REPORT_ROLLBACK, job["job_id"], job["requested_version"],
        job["started_at"], job["finished_at"],
    ]


def capture_backups(data: Path) -> dict[str, str]:
    env, compose = _backups(data)
    return {
        "env": env.name, "env_digest": digest_of(_read(env, 256 * 1024)),
        "compose": compose.name, "compose_digest": digest_of(_read(compose, COMPOSE_LIMIT)),
    }


def _empty_journal(path: Path, instance: UUID) -> None:
    if not path.is_file():
        raise ValueError("The managed journal cannot be verified")
    try:
        with closing(sqlite3.connect(f"{safe_path(path).as_uri()}?mode=ro", uri=True)) as db:
            if (
                db.execute("PRAGMA application_id").fetchone()[0] != 0x44565449
                or db.execute("PRAGMA user_version").fetchone()[0] != FORMAT_VERSION
            ):
                raise ValueError("The managed journal format is unsupported")
            if db.execute("SELECT 1 FROM operations LIMIT 1").fetchone():
                raise ValueError("An admitted operation already owns this installation")
            owners = db.execute("SELECT instance_id FROM identity").fetchall()
            if any(owner != str(instance) for (owner,) in owners):
                raise ValueError("The managed journal belongs to another instance")
    except sqlite3.Error as error:
        raise ValueError("The managed journal could not be read during recovery") from error


def _quarantine_unadmitted(data: Path, marker: dict, image: str, instance: UUID) -> None:
    _, token = _handoff_identity(marker)
    quarantine = safe_path(data / "installation" / (".legacy-unadmitted-" + token))
    present = [name for name in (CONTROL, STATE) if os.path.lexists(data / name)]
    if not present:
        return
    if marker.get("managed_paths_absent") is not True:
        raise ValueError("Managed recovery owns this installation")
    control = (data if CONTROL in present else quarantine) / CONTROL
    if os.path.lexists(control / "current-release.json"):
        raise ValueError("A managed release already owns this installation")
    config = json.loads(_read(control / "host.json", 128 * 1024))
    if (
        config["version"] != 1 or config["instance"] != str(instance)
        or config["data"] != str(data) or config["project"] != marker["project"]
        or any(config[key] != image for key in ("executor", "manager", "candidate"))
    ):
        raise ValueError("The partial bootstrap belongs to another instance")
    journal_root = (data if STATE in present else quarantine) / STATE
    if os.path.lexists(journal_root):
        _empty_journal(journal_root / "journal.sqlite3", instance)

    ids = docker("container", "ls", "--quiet", "--filter", f"ancestor={image}").stdout.split()
    if ids:
        rows = json.loads(docker("container", "inspect", *ids).stdout)
        if any(row["Config"].get("Cmd") == ["candidate-init", str(data)] for row in rows):
            raise ValueError("The bootstrap initializer is still running")
    quarantine.mkdir(mode=0o700, exist_ok=True)
    for name in present:
        source, saved = safe_path(data / name), safe_path(quarantine / name)
        if os.path.lexists(saved):
            raise ValueError("The partial bootstrap quarantine is already occupied")
        source.rename(saved)
        sync_directory(quarantine)
        sync_directory(data)


def restore_before_admission(data: Path, marker: dict, image: str) -> None:
    if marker.get("managed_paths_absent") is not True and any(
        os.path.lexists(data / name) for name in (CONTROL, STATE)
    ):
        raise ValueError("Managed recovery owns this installation")
    project = marker["project"]
    if capture_backups(data) != marker.get("backups"):
        raise ValueError("The old update backups have changed")
    env, compose = (data / marker["backups"][key] for key in ("env", "compose"))
    model, values = _old_model(data, project, env, compose)
    roles = _containers(project)
    check_historical_migrator(roles, model["services"])
    if not roles.keys() >= CORE or roles.keys() - CORE - APPLICATION - {"migrate"}:
        raise ValueError("Legacy services could not be confirmed for automatic recovery")
    [manager] = roles["installation_manager"]
    [postgres] = roles["postgres"]
    [valkey] = roles["valkey"]
    if not _is_legacy_manager(manager, project, data):
        raise ValueError("The updating manager no longer owns the installation")
    [binding] = _source_service(manager).bindings
    identity = InstanceIdentity(
        UUID(_read(data / "installation" / "instance_id", 128).decode().strip()), str(data),
        project, binding.address, binding.port, values["DVT_PUBLIC_URL"].split(";", 1)[0],
    )
    for role, row in (("postgres", postgres), ("valkey", valkey)):
        if not row["State"]["Running"] or not _same_service(
            _source_service(row), _target_service(role, model["services"][role], model, identity),
        ):
            raise ValueError("Legacy storage configuration changed")
    revision = ComposeMaintenanceHost.sql(postgres["Id"], "SELECT version_num FROM alembic_version")
    legacy_source_version(values["DVT_VERSION"], revision)

    pinned = _pin_fallback(model, values)
    if pinned is None:
        raise ValueError("A historical application image is missing from local storage")
    fallback = json.loads(pinned)
    images = {
        role: check_image(service["image"]) for role, service in fallback["services"].items()
    }
    if any(roles[role][0]["Image"] != images[role] for role in CORE):
        raise ValueError("Legacy infrastructure was replaced")
    for role, rows in roles.items():
        if role in CORE or role == "migrate":
            continue
        for row in rows:
            labels = row["Config"]["Labels"]
            if not (
                (labels.get(LABEL) == "1" and row["Config"]["Image"] == image)
                or row["Image"] == images.get(role)
                or (role == "dvt-ai-mcp" and not row["State"]["Running"])
            ):
                raise ValueError("A container outside the historical update is present")
    targets = sorted(images.keys() & APPLICATION)
    workers = int(values.get("DVT_TASK_WORKERS_COUNT", "1"))
    if not targets or workers < 1:
        raise ValueError("The historical deployment settings are invalid")

    # Keep exact backups in the usual paths. Run only the application roles and
    # use their locally resolved image digests to avoid substituting mutable tags.
    _quarantine_unadmitted(data, marker, image, identity.instance_id)
    atomic_write(data / ".env", _read(env, 256 * 1024))
    atomic_write(data / "docker-compose.yaml", _read(compose, COMPOSE_LIMIT))
    with NamedTemporaryFile(prefix=".legacy-return-", suffix=".json", dir=data) as pinned_file:
        pinned_file.write(pinned)
        pinned_file.flush()
        docker(
            "compose", "--project-name", project, "--project-directory", str(data),
            "--env-file", "/dev/null", "--file", pinned_file.name, "--profile", "*",
            "up", "--detach", "--no-deps", "--no-build", "--pull", "never",
            "--scale", f"task-worker={workers}", *targets,
        )
    restarted = _containers(project)
    if any(
        not restarted.get(role)
        or any(row["Image"] != images[role] or not row["State"]["Running"]
               for row in restarted[role])
        for role in targets
    ):
        raise ValueError("Compose did not restore the historical application")

    configure_rollback_manager(fallback, rollback_job(marker))
    # Keep the original Compose and dotenv on disk. Only this one container
    # needs the temporary command to report the completed rollback in the old UI.
    with NamedTemporaryFile(prefix=".legacy-status-", suffix=".json", dir=data) as status_file:
        status_file.write(canonical_json(fallback))
        status_file.flush()
        docker(
            "compose", "--project-name", project, "--project-directory", str(data),
            "--env-file", "/dev/null", "--file", status_file.name,
            "up", "--detach", "--wait", "--wait-timeout", "45",
            "--no-deps", "--no-build", "--pull", "never", "installation_manager",
        )
