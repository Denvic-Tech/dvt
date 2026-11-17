"""Real PostgreSQL portable-copy test, without published ports or application containers.

Run as root with the project venv and PYTHONPATH on two isolated Docker Linux hosts.
Transfer only the fixture-generated COPY directory, preserving private modes.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from uuid import UUID, uuid4

from services.installation_manager.application.portable_restore import inspect_copy, restore_data
from services.installation_manager.domain.operation_state import (
    ArtifactKind,
    Checkpoint,
    CheckpointOutcome,
    InstanceIdentity,
    Observation,
    OperationKind,
    OperationRequest,
    OperationStage,
    ReleasePin,
)
from services.installation_manager.domain.release_manifest import canonical_json, digest_of
from services.installation_manager.host_bootstrap import check_image, docker, safe_path
from services.installation_manager.infrastructure.maintenance_archive import (
    create_copy,
    preflight,
)
from services.installation_manager.infrastructure.maintenance_database import frozen_sql
from services.installation_manager.infrastructure.maintenance_host import ComposeMaintenanceHost
from services.installation_manager.infrastructure.operation_store import OperationStore
from services.installation_manager.infrastructure.staging_artifacts import (
    artifact_directory,
    write_artifact,
)

FOLDER = re.compile(r"dvt-s06-[0-9a-f]{12}")
REVISION = "0070"
DSN = {
    "POSTGRES_USER": "fixture-user",
    "POSTGRES_PASSWORD": "stage06-non-secret",
    "POSTGRES_DB": "stage06",
}


def start(pgdata: Path, project: str, image: str) -> str:
    name = f"{project}-fixture-{uuid4().hex[:8]}"
    pgdata.mkdir(mode=0o700, parents=True, exist_ok=True)
    options = [entry for key, value in DSN.items() for entry in ("--env", f"{key}={value}")]
    return docker(
        "run", "--detach", "--rm", "--network", "none", "--name", name, "--pull=never",
        "--label", f"dvt.test.scope={project}",
        "--mount", f"type=bind,src={pgdata},dst=/var/lib/postgresql/data",
        *options, image,
    ).stdout.strip()


def wait(container: str) -> None:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        result = docker(
            "exec", container, "pg_isready", "-h", "127.0.0.1",
            "-U", DSN["POSTGRES_USER"], "-d", DSN["POSTGRES_DB"],
            check=False, timeout=8,
        )
        if result.returncode == 0:
            return
        time.sleep(1)
    raise RuntimeError("Fixture PostgreSQL did not start")


def stop(container: str) -> None:
    docker("container", "stop", "--timeout=60", container, check=False, timeout=70)
    docker("container", "rm", "--force", container, check=False, timeout=75)


def create(root: Path, project: str, image: str) -> dict:
    check_image(image)
    root.mkdir(mode=0o700)
    data, backup, temporary = (root / name for name in ("instance", "copy", "tmp"))
    pgdata = data / "data" / "pgdata"
    for folder in (data, backup, temporary, data / ".bootstrap", data / "extensions",
                   data / "installation"):
        folder.mkdir(mode=0o700)
    identity = InstanceIdentity(uuid4(), str(data), project, "127.0.0.1", 19147,
                                "http://localhost:18147")
    host = {
        "version": 1, "instance": str(identity.instance_id), "data": str(data),
        "project": project, "address": identity.manager_address, "port": identity.manager_port,
        "public_url": identity.public_url, "backup": str(backup), "temporary": str(temporary),
    }
    write_artifact(data / ".bootstrap" / "host.json", canonical_json(host))
    env = b"DVT_FIXTURE=synthetic\n"
    write_artifact(data / ".env", env)
    write_artifact(data / "extensions" / "fixture.py", b"VALUE = 'fixture-extension'\n")
    write_artifact(data / "installation" / "marker", b"before-copy\n")
    compose = canonical_json({
        "name": project,
        "services": {
            "postgres": {
                "environment": DSN, "image": image,
                "volumes": [
                    {"type": "bind", "source": str(pgdata), "target": "/var/lib/postgresql/data"},
                ],
            },
        },
    })
    write_artifact(data / "docker-compose.yaml", compose)
    store = OperationStore.for_host(data)
    store.establish_identity(identity)
    source = "sha256:" + "a" * 64
    operation = store.admit(
        OperationRequest(OperationKind.UPDATE, ReleasePin("fixture", "sha256:" + "b" * 64)),
        idempotency_key="portable-fixture",
    )
    write_artifact(data / ".bootstrap" / "current-release.json", canonical_json({
        "instance": str(identity.instance_id), "manifest_digest": source, "revision": REVISION,
        "compose_digest": digest_of(compose), "config_digest": digest_of(env),
        "images": {"postgres": image},
    }))
    with store.claim(operation.id) as owner:
        owner.checkpoint(Checkpoint(OperationStage.PREPARING))
        owner.checkpoint(Checkpoint(
            OperationStage.PREPARED, CheckpointOutcome.VERIFIED,
            observation=Observation(
                staging_id=operation.id, source_digest=source, source_revision=REVISION,
            ),
        ))
        owner.checkpoint(Checkpoint(OperationStage.MAINTENANCE))
        owner.checkpoint(Checkpoint(OperationStage.BACKUP))
    container = start(pgdata, project, image)
    try:
        wait(container)
        sql = ComposeMaintenanceHost.sql
        sql(container, f"""
            CREATE TABLE alembic_version (version_num varchar primary key);
            INSERT INTO alembic_version VALUES ('{REVISION}');
            CREATE TABLE task_admission_control (
                singleton int primary key, operation_id uuid, frozen boolean NOT NULL
            );
            INSERT INTO task_admission_control VALUES (1, '{operation.id}', true);
            CREATE TABLE tasks (task_id text primary key, status text NOT NULL);
            INSERT INTO tasks VALUES ('terminal-fixture', 'SUCCESS');
            CREATE TABLE portable_fixture (value text primary key);
            INSERT INTO portable_fixture VALUES ('before-copy');
        """)
        meta = {
            "operation_id": str(operation.id), "backup_id": str(operation.id),
            "instance_id": str(identity.instance_id), "source_revision": REVISION,
            "source_digest": source, "source_images": {"postgres": image},
            "compose_project": project, "profiles": [], "containers": [],
            "layout": preflight(data, backup, temporary, pgdata),
            "schedule_policy": "skip_cron_preserve_existing_retries",
            "queue_policy": "drain_admitted_cancel_unadmitted_roots",
        }
        staging = artifact_directory(store, ArtifactKind.STAGING, operation.id)
        write_artifact(staging / "maintenance.json", canonical_json(meta))
        create_copy(
            backup, operation.id, {"format_version": 1, **meta},
            ComposeMaintenanceHost(host, operation.id, {"postgres": image}), container,
            confirm_source_sealed=lambda: sql(container, frozen_sql(operation.id)) == "frozen",
        )
        sql(container, "INSERT INTO portable_fixture VALUES ('after-copy')")
    finally:
        stop(container)
    archive = backup / str(operation.id)
    _, plan = inspect_copy(archive)
    return {**plan, "copy": str(archive), "data": str(data), "postgres_image": image}


def verify(root: Path, project: str, image: str, args) -> dict:
    backup = root / "copy" / str(UUID(args.backup_id))
    data = root / "instance"
    output = restore_data(data, backup, args.confirm_manifest, args.confirm_loss_after)
    if (data / "extensions" / "fixture.py").read_bytes() != b"VALUE = 'fixture-extension'\n":
        raise ValueError("Fixture extension differs")
    if (data / "installation" / "marker").read_bytes() != b"before-copy\n":
        raise ValueError("Fixture persistent file differs")
    store = OperationStore.for_host(data)
    if store.active().id != UUID(args.backup_id) or store.identity().compose_project != project:
        raise ValueError("Fixture journal or identity differs")
    container = start(data / "data" / "pgdata", project, image)
    try:
        wait(container)
        sql = ComposeMaintenanceHost.sql
        if sql(container, "SELECT value FROM portable_fixture") != "before-copy":
            raise ValueError("Unexpected restore time boundary")
        if sql(container, "SELECT status FROM tasks") != "SUCCESS":
            raise ValueError("Unexpected restored terminal task")
        if sql(container, frozen_sql(UUID(args.backup_id))) != "frozen":
            raise ValueError("The restored admission must stay frozen")
    finally:
        stop(container)
    return {**output, "file": "verified", "extension_file": "verified",
            "terminal_task": "verified", "post_copy_record": "absent"}


def main() -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["create", "verify"])
    parser.add_argument("--scope", required=True, type=Path)
    parser.add_argument("--postgres", required=True)
    parser.add_argument("--backup-id")
    parser.add_argument("--confirm-manifest")
    parser.add_argument("--confirm-loss-after")
    args = parser.parse_args()
    root = safe_path(args.scope)
    if root.parent != Path("/var/tmp") or not FOLDER.fullmatch(root.name):
        raise ValueError("Use /var/tmp/dvt-s06-<12 lowercase hex digits>")
    result = (
        create(root, root.name, args.postgres) if args.action == "create"
        else verify(root, root.name, args.postgres, args)
    )
    sys.stdout.write(json.dumps(result, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
