"""Linux-only maintenance smoke on new temporary Docker scopes and local files.

Run as root using an isolated fixture host, with the DVT venv and repository on
PYTHONPATH. Requires cached or pullable postgres:15.3-alpine; needs no registry,
real DVT images, credentials, host reboot, application migration or restore.
"""

from __future__ import annotations

import json
import os
import subprocess
import tarfile
import time
from contextlib import ExitStack, suppress
from multiprocessing import get_context
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from services.installation_manager.application import maintenance_backup
from services.installation_manager.domain.operation_state import (
    ArtifactKind,
    Checkpoint,
    CheckpointOutcome,
    FailureReason,
    InstanceIdentity,
    Observation,
    OperationKind,
    OperationRequest,
    OperationStage,
    ReleasePin,
)
from services.installation_manager.domain.release_manifest import canonical_json
from services.installation_manager.host_bootstrap import docker
from services.installation_manager.infrastructure import maintenance_host
from services.installation_manager.infrastructure.maintenance_host import ComposeMaintenanceHost
from services.installation_manager.infrastructure.operation_store import OperationStore
from services.installation_manager.infrastructure.staging_artifacts import (
    artifact_directory,
    write_artifact,
)

PG = "postgres:15.3-alpine"
SOURCE = ReleasePin("smoke-source", "sha256:" + "a" * 64)
TARGET = ReleasePin("smoke-target", "sha256:" + "b" * 64)
FIXTURE_CREDENTIAL = "stage-04-test-only"


def cleanup(*args: str) -> None:
    with suppress(OSError, subprocess.SubprocessError):
        docker(*args, check=False)


def eventually(fn) -> None:
    end = time.monotonic() + 30
    while time.monotonic() < end:
        try:
            if fn():
                return
        except (OSError, subprocess.SubprocessError):
            pass
        time.sleep(0.25)
    raise RuntimeError("The scoped smoke fixture was not ready")


def scenario() -> None:
    os.umask(0o077)
    project = f"dvt-s04-{uuid4().hex[:12]}"
    instance = uuid4()
    label = f"com.docker.compose.project={project}"
    image = f"{project}:fixture"
    image_ref = "docker.io/library/stage04-synthetic@sha256:" + "c" * 64
    with ExitStack() as cleanup_scope:
        root = Path(cleanup_scope.enter_context(TemporaryDirectory(prefix=f"{project}-", dir="/var/tmp")))
        backup = Path(cleanup_scope.enter_context(TemporaryDirectory(prefix=f"{project}-", dir="/dev/shm")))
        data = root / "dvt"
        temporary = root / "tmp"
        for folder in (data, temporary, data / "installation", data / "extensions", data / ".bootstrap"):
            folder.mkdir(mode=0o700)
        (data / ".env").write_text("DVT_SYNTHETIC_TEST=1\n")
        (data / "docker-compose.yaml").write_text("name: " + project + "\n")
        (data / "installation" / "instance_id").write_text(str(instance))
        (data / "extensions" / "fixture.py").write_text("SAMPLE = 'stage04'\n")
        (data / ".bootstrap" / "host.json").write_text("{}\n")

        assert data.stat().st_dev != backup.stat().st_dev, "The backup fixture needs a distinct FS"
        assert docker("image", "inspect", PG, check=False).returncode == 0, "Pull fixture PostgreSQL first"
        build = root / "build"
        build.mkdir()
        entrypoint = [
            "sh", "-c", 'if [ "$1" = writer ]; then '
            "while :; do echo sample >> /dvt-files/marker; sleep 1; done; "
            "else exec sleep 3600; fi", "stage04-fixture",
        ]
        (build / "Dockerfile").write_text(
            f"FROM {PG}\nLABEL tech.denvic.task-admission=1\n"
            f"ENTRYPOINT {json.dumps(entrypoint)}\n"
        )
        cleanup_scope.callback(cleanup, "image", "rm", image)
        docker("build", "--pull=false", "--tag", image, str(build), timeout=180)
        (dummy,) = json.loads(docker("image", "inspect", image).stdout)
        (postgres_image,) = json.loads(docker("image", "inspect", PG).stdout)
        found = maintenance_host.image_references
        postgres_ref = next(iter(found(postgres_image)))
        # Only the locally built synthetic writer has no registry digest. The
        # real PostgreSQL image exercises production RepoDigest normalization.
        maintenance_host.image_references = lambda inspected: (
            {image_ref} if inspected["Id"] == dummy["Id"] else found(inspected)
        )

        docker("network", "create", project)
        cleanup_scope.callback(cleanup, "network", "rm", project)
        env = []
        for key, value in (
            ("POSTGRES_USER", "stage04"),
            ("POSTGRES_DB", "stage04"),
            ("POSTGRES_HOST", "postgres"),
            ("POSTGRES_PASSWORD", FIXTURE_CREDENTIAL),
        ):
            env.extend(("--env", f"{key}={value}"))

        def run(role: str, ref: str, *options: str, entry: tuple[str, ...] = ()) -> str:
            name = f"{project}-{role}"
            cleanup_scope.callback(cleanup, "container", "rm", "-f", name)
            return docker(
                "run", "--detach", "--pull=never", "--name", name,
                "--network", project, "--network-alias", role, "--restart", "always",
                "--label", label, "--label", f"com.docker.compose.service={role}",
                *env, *options, ref, *entry,
            ).stdout.strip()

        pgdata = data / "pgdata"
        pgdata.mkdir(mode=0o700)
        db = run("postgres", PG, "--volume", f"{pgdata}:/var/lib/postgresql/data")
        roles = {role: image_ref for role in maintenance_host.CORE_SERVICES if role != "postgres"}
        ids = {}
        for role in roles:
            entry = ("candidate-web", str(data)) if role == "installation_manager" else (
                ("writer",) if role == "gateway" else ("idle",)
            )
            ids[role] = run(
                role, image,
                "--volume", f"{data / 'installation'}:/var/lib/postgresql/data",
                "--volume", f"{data / 'installation'}:/dvt-files",
                entry=entry,
            )
        roles["postgres"] = postgres_ref
        sql = ComposeMaintenanceHost.sql
        eventually(lambda: sql(db, "SELECT 1") == "1")
        sql(db, """
            CREATE TABLE alembic_version (version_num varchar primary key);
            INSERT INTO alembic_version VALUES ('0070');
            CREATE TABLE task_admission_control (
                singleton int primary key, operation_id uuid, frozen boolean NOT NULL DEFAULT false
            );
            INSERT INTO task_admission_control (singleton) VALUES (1);
            CREATE TABLE tasks (
                task_id text primary key, status varchar NOT NULL, source varchar NOT NULL,
                prepared_by_parent_id text, termination_reason text, message text,
                updated_at timestamptz, finished_at timestamptz
            );
            CREATE TABLE task_dispatch_outbox (task_id text primary key);
            CREATE TABLE verified_payload (id int primary key, content text);
            INSERT INTO verified_payload VALUES (1, 'archive fixture');
            INSERT INTO tasks VALUES ('active', 'RUNNING', 'API', NULL, NULL, NULL, now(), NULL);
        """)
        eventually((data / "installation" / "marker").is_file)

        store = OperationStore.for_host(data)
        store.establish_identity(
            InstanceIdentity(instance, str(data), project, "127.0.0.1", 8443, "https://localhost:8443")
        )
        request = OperationRequest(OperationKind.UPDATE, TARGET, config_id=uuid4())
        operation = store.admit(request, idempotency_key="smoke-apply").id
        with store.claim(operation) as owner:
            owner.checkpoint(Checkpoint(OperationStage.PREPARING))
            owner.checkpoint(Checkpoint(
                OperationStage.PREPARED, CheckpointOutcome.VERIFIED,
                observation=Observation(
                    source_digest=SOURCE.manifest_digest, source_revision="0070",
                    target_digest=TARGET.manifest_digest, staging_id=operation,
                ),
            ))
        staging = artifact_directory(store, ArtifactKind.STAGING, operation)
        write_artifact(staging / "plan.json", canonical_json({
            "format_version": 1, "manifest_digest": TARGET.manifest_digest,
            "config_id": str(request.config_id), "applied_manifest_digest": SOURCE.manifest_digest,
            "observed_revision": "0070", "profiles": [], "observed_images": roles,
            "transition": {"migration": "from_revision"},
        }))

        config = {
            "data": str(data), "backup": str(backup), "temporary": str(temporary),
            "instance": str(instance), "project": project,
            "manager": image_ref, "candidate": image_ref, "executor": image_ref,
        }
        context = get_context("fork")

        def executor(**kwargs) -> None:
            maintenance_backup.MaintenanceBackup(
                OperationStore.for_host(data), config
            ).execute(operation, **kwargs)

        def run_executor(**kwargs) -> None:
            child = context.Process(target=executor, kwargs=kwargs)
            child.start()
            child.join(90)
            if child.is_alive():
                child.kill()
                child.join()
                raise RuntimeError("The fixture executor did not finish")
            assert child.exitcode == 0

        maintenance_backup.DRAIN_SECONDS = 0
        run_executor(confirm=True)
        assert store.get(operation).stage is OperationStage.MAINTENANCE
        assert store.events(operation)[-1].checkpoint.reason is FailureReason.MAINTENANCE_DRAIN_TIMEOUT
        assert sql(db, "SELECT operation_id FROM task_admission_control") == str(operation)
        assert sql(db, "SELECT frozen FROM task_admission_control") == "f"
        assert not list(backup.iterdir())
        print("closed, active task retained, deadline persisted", flush=True)  # noqa: T201 - CLI progress

        prior_claim = store.get(operation).last_owner.claim_id
        maintenance_backup.DRAIN_SECONDS = 300
        interrupted = context.Process(target=executor, kwargs={"extend": True})
        interrupted.start()
        try:
            eventually(lambda: store.get(operation).last_owner.claim_id != prior_claim)
        finally:
            if interrupted.is_alive():
                interrupted.kill()
            interrupted.join()
        assert interrupted.exitcode < 0
        assert sql(db, "SELECT operation_id FROM task_admission_control") == str(operation)
        assert not list(backup.iterdir())
        print("killed executor; persisted gate remained closed", flush=True)  # noqa: T201 - CLI progress

        sql(db, "UPDATE tasks SET status='SUCCESS' WHERE task_id='active'")
        run_executor()
        result = store.get(operation)
        assert result.stage is OperationStage.BACKUP and result.observation.backup_id == operation
        assert sql(db, "SELECT frozen FROM task_admission_control") == "t"
        for role, container in ids.items():
            (details,) = json.loads(docker("container", "inspect", container).stdout)
            assert details["State"]["Running"] == (role == "installation_manager")
            if role != "installation_manager":
                assert details["HostConfig"]["RestartPolicy"]["Name"] == "no"

        point = backup / str(operation)
        manifest = json.loads((point / "manifest.json").read_text())
        assert manifest["layout"]["separate_filesystem"]
        assert manifest["source_images"]["postgres"] == postgres_ref
        assert manifest["source_revision"] == "0070"
        assert manifest["instance_id"] == str(instance)
        assert all(item["restart"]["Name"] == "always" for item in manifest["containers"])
        marker = (data / "installation" / "marker").read_bytes()
        with tarfile.open(point / "data.tar.gz") as archive:
            assert archive.extractfile("installation/marker").read() == marker
            assert archive.extractfile("extensions/fixture.py").read() == b"SAMPLE = 'stage04'\n"
            assert archive.extractfile("installation/instance_id").read() == str(instance).encode()
        # Fully decoding the PostgreSQL custom dump checks data readability
        # without restoring anything into an existing database.
        dump_sql = subprocess.run(
            ["docker", "exec", "-i", db, "pg_restore", "-f", "-"],
            input=(point / "database.dump").read_bytes(), capture_output=True, check=True,
        ).stdout
        assert b"archive fixture" in dump_sql
        assert b"task_admission_control" in dump_sql and str(operation).encode() in dump_sql
        time.sleep(1.1)
        assert (data / "installation" / "marker").read_bytes() == marker
        print(  # noqa: T201 - CLI progress
            "all fixture writers stopped; manager available; matching dumps and portable files verified",
            flush=True,
        )


if __name__ == "__main__":
    scenario()
