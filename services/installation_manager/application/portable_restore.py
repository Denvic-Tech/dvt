"""Recover a verified backup into an absent DVT data directory with admission still frozen."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
import sys
import tarfile
import time
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from uuid import UUID, uuid4

from ..domain.operation_state import ArtifactKind, OperationKind, OperationStage
from ..domain.release_manifest import canonical_json, digest_of, strict_json
from ..host_bootstrap import (
    CONTROL,
    DOCKER_ENV,
    PROJECT,
    SOCKET,
    check_image,
    check_project,
    docker,
    safe_path,
)
from ..infrastructure.maintenance_archive import read_copy_manifest, verify_copy_files
from ..infrastructure.maintenance_database import DATABASE_PROFILE, frozen_sql
from ..infrastructure.maintenance_host import PG_TARGET, ComposeMaintenanceHost
from ..infrastructure.operation_files import sync_directory
from ..infrastructure.operation_store import OperationStore
from ..infrastructure.staging_artifacts import artifact_directory, read_artifact, write_artifact
from ..infrastructure.staging_compose import COMPOSE_LIMIT
from ..infrastructure.staging_docker import _compose_value
from .recovery import import_source_failure

LIMIT = 256 * 1024
SAFE_DB_ID = re.compile(r"[a-zA-Z0-9_.-]{1,63}")
CONTAINER_ID = re.compile(r"[0-9a-f]{64}")
PG_READY = 80


def _read(path: Path, limit: int = LIMIT) -> dict:
    raw = read_artifact(path, limit)
    if raw is None:
        raise ValueError("A required restoration artifact is missing")
    value = strict_json(raw)
    if not isinstance(value, dict):
        raise TypeError("Invalid restoration configuration")
    return value


def inspect_copy(backup: Path) -> tuple[dict, dict]:
    raw, meta = read_copy_manifest(safe_path(backup))
    backup_id = UUID(meta["backup_id"])
    if (
        meta["format_version"] != 1
        or backup_id != UUID(meta["operation_id"])
        or not backup_id.int
        or not UUID(meta["instance_id"]).int
        or not PROJECT.fullmatch(meta["compose_project"])
        or datetime.fromisoformat(meta["created_at"]) > datetime.now(UTC)
        or not re.fullmatch(r"[0-9a-f]{4,32}", meta["source_revision"])
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", meta["source_digest"])
    ):
        raise ValueError("Unsupported recovery point contract")
    return meta, {
        "format_version": 1,
        "backup_id": str(backup_id),
        "manifest_digest": digest_of(raw),
        "created_at": meta["created_at"],
        "source_revision": meta["source_revision"],
        "source_manifest_digest": meta["source_digest"],
        "data_loss": "Records after created_at and effects in external systems are not restored",
        "action": "restore_data_on_clean_host",
    }


def _archive_filter(member: tarfile.TarInfo, directory: str) -> tarfile.TarInfo:
    # Use the containment and file-type checks of the stdlib. Keep uid/gid and ordinary
    # mode bits from the source because PostgreSQL/Valkey/application run as different UIDs.
    tarfile.data_filter(member, directory)
    return tarfile.tar_filter(member, directory)


def extract_data(path: Path, destination: Path) -> None:
    if any(destination.iterdir()):
        raise ValueError("The restore scratch directory must be empty")
    with tarfile.open(path, mode="r:gz") as archive:
        kinds: dict[PurePosixPath, str] = {}
        links = []
        for member in archive:
            name = PurePosixPath(member.name)
            if (
                not name.parts or name.is_absolute() or ".." in name.parts
                or member.name != name.as_posix() or name in kinds
                or len(kinds) >= 1_000_000
            ):
                raise ValueError("The backup has an unsafe member path")
            if member.isdir():
                kinds[name] = "directory"
            elif member.isfile() or member.islnk():
                if member.islnk() and kinds.get(PurePosixPath(member.linkname)) != "file":
                    raise ValueError("The backup has an unverified hardlink target")
                kinds[name] = "file"
            elif member.issym():
                target = name.parent / PurePosixPath(member.linkname)
                if target.is_absolute():
                    raise ValueError("The backup contains an absolute symlink")
                links.append((name, target))
                kinds[name] = "symlink"
            else:
                raise ValueError("The backup contains a special file")
        if any(
            kinds.get(parent) != "directory"
            for path in kinds for parent in path.parents if parent.parts
        ):
            raise ValueError("A backup member has an unexpected parent")
        for _, target in links:
            parts = []
            for part in target.parts:
                if part == "..":
                    if not parts:
                        raise ValueError("A backup symlink leaves the data directory")
                    parts.pop()
                else:
                    parts.append(part)
            # Symlinks are allowed only to existing regular files/directories.
            if kinds.get(PurePosixPath(*parts)) not in {"file", "directory"}:
                raise ValueError("A backup symlink does not refer to a verified member")
        archive.extractall(destination, filter=_archive_filter)


def _source(scratch: Path, destination: Path, metadata: dict):
    config = _read(scratch / CONTROL / "host.json")
    source = _read(scratch / CONTROL / "current-release.json")
    compose = read_artifact(scratch / "docker-compose.yaml", 8 * COMPOSE_LIMIT)
    env = read_artifact(scratch / ".env", LIMIT)
    store = OperationStore.for_host(scratch)
    identity = store.identity()
    operation_id = UUID(metadata["operation_id"])
    active = store.active()
    if (
        not identity or not active
        or active.id != operation_id
        or active.request.kind is not OperationKind.UPDATE
        or active.stage is not OperationStage.BACKUP
        or active.observation.source_revision != metadata["source_revision"]
        or active.observation.source_digest != metadata["source_digest"]
        or str(identity.instance_id) != metadata["instance_id"]
        or identity.data_dir != str(destination)
        or identity.compose_project != metadata["compose_project"]
        or (
            config["instance"], config["data"], config["project"],
            config["address"], config["port"], config["public_url"],
        ) != (
            metadata["instance_id"], str(destination), metadata["compose_project"],
            identity.manager_address, identity.manager_port, identity.public_url,
        )
        or source["instance"] != metadata["instance_id"]
        or source["manifest_digest"] != metadata["source_digest"]
        or source["revision"] != metadata["source_revision"]
        or {
            role: image for role, image in source["images"].items() if role != "migrate"
        } != metadata["source_images"]
        or compose is None or env is None
        or source["compose_digest"] != digest_of(compose)
        or source["config_digest"] != digest_of(env)
    ):
        raise ValueError("The backup and saved source instance do not match")
    staging = artifact_directory(store, ArtifactKind.STAGING, operation_id)
    portable_metadata = {
        name: value for name, value in metadata.items()
        if name not in {"format_version", "created_at", "artifacts"}
    }
    if _read(staging / "maintenance.json") != portable_metadata:
        raise ValueError("The backup differs from the original maintenance observation")
    model = _compose_value(strict_json(compose))
    pg = model["services"]["postgres"]
    path = metadata["layout"]["postgres_data"]
    if (
        not isinstance(path, str) or path in {"", "."} or path.startswith("/")
        or Path(path).as_posix() != path or ".." in Path(path).parts or "." in Path(path).parts
        or (scratch / path).exists()
        or (scratch / path).resolve() != scratch / path
        or pg["image"] != metadata["source_images"]["postgres"]
        or not isinstance(pg["volumes"], list) or len(pg["volumes"]) != 1
        or pg["volumes"][0]["source"] != str(destination / path)
        or pg["volumes"][0]["target"] != PG_TARGET
        or pg["volumes"][0]["type"] != "bind" or pg["volumes"][0].get("read_only")
    ):
        raise ValueError("The recovery point contains a foreign or unsafe PostgreSQL path")
    return scratch / path, pg["image"], pg["environment"], operation_id, staging


def _pg_command(container: str, command: str, *values: str, stdin) -> None:
    subprocess.run(
        [
            "docker", "--host", f"unix://{SOCKET}", "exec", "--interactive", container,
            "sh", "-ec", command, "dvt-portable-restore", *values,
        ],
        env=DOCKER_ENV, stdin=stdin, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        check=True, timeout=3600,
    )


def _without_initial_role(source: Path, role_sql: str) -> bytes:
    if source.stat().st_size > LIMIT:
        raise ValueError("Unsupported globals dump size")
    contents = source.read_bytes()
    line = f"CREATE ROLE {role_sql};\n".encode()
    if contents.count(line) != 1 or not contents.startswith(b"--\n-- PostgreSQL"):
        raise ValueError("The PostgreSQL globals dump does not match the bootstrap role")
    return contents.replace(line, b"", 1)


def _restore_database(
    directory: Path, pgdata: Path, image: str, environment: dict, operation_id: UUID, revision: str,
) -> None:
    user, db = environment["POSTGRES_USER"], environment["POSTGRES_DB"]
    if (
        not SAFE_DB_ID.fullmatch(user) or not SAFE_DB_ID.fullmatch(db)
        or db in {"postgres", "template0", "template1"} or environment.get("PGDATA", PG_TARGET) != PG_TARGET
        or not environment["POSTGRES_PASSWORD"]
    ):
        raise ValueError("This recovery profile requires a dedicated, simple PostgreSQL database")
    expected_image = check_image(image)
    pgdata.mkdir(mode=0o700, parents=True)
    # The isolated recovery container leaves an ordinary SCRAM HBA; globals.sql restores
    # the original role hash. Docker never publishes a database port.
    name = f"dvt-restore-{uuid4().hex}"
    result = docker(
        "run", "--detach", "--rm", "--pull=never", "--network", "none", "--name", name,
        "--label", f"dvt.recovery.operation={operation_id}",
        "--mount", f"type=bind,src={pgdata},dst={PG_TARGET}",
        "--env", f"POSTGRES_USER={user}", "--env", "POSTGRES_DB=postgres",
        "--env", f"POSTGRES_PASSWORD={uuid4().hex}",
        "--env", "POSTGRES_HOST_AUTH_METHOD=scram-sha-256", image,
    )
    container = result.stdout.strip()
    if not CONTAINER_ID.fullmatch(container):
        raise ValueError("Docker returned an invalid recovery container ID")
    try:
        (observed,) = json.loads(docker("container", "inspect", container).stdout)
        if (
            observed["Image"] != expected_image
            or observed["HostConfig"]["NetworkMode"] != "none"
            or observed["HostConfig"].get("PortBindings")
        ):
            raise ValueError("The isolated PostgreSQL container was not created")
        until = time.monotonic() + PG_READY
        while True:
            # TCP only answers after initdb's private startup has finished.
            pg_ready = docker(
                "exec", container, "pg_isready", "-h", "127.0.0.1", "-U", user, "-d", "postgres",
                check=False, timeout=8,
            )
            if pg_ready.returncode == 0:
                break
            if time.monotonic() >= until:
                raise TimeoutError("Isolated PostgreSQL did not start")
            time.sleep(1)
        role_sql = ComposeMaintenanceHost.sql(container, "SELECT quote_ident(current_user)")
        with TemporaryDirectory(prefix=".globals-", dir=pgdata.parent) as temporary:
            sql = Path(temporary) / "globals.sql"
            write_artifact(sql, _without_initial_role(directory / "globals.sql", role_sql))
            with sql.open("rb") as stream:
                _pg_command(
                    container,
                    'exec psql -Xq -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d postgres',
                    stdin=stream,
                )
        with (directory / "database.dump").open("rb") as stream:
            _pg_command(
                container, 'exec pg_restore --exit-on-error --create -U "$POSTGRES_USER" -d postgres',
                stdin=stream,
            )
        # Authenticate with the prior application password, verified through a stream.
        checks = (
            "SHOW data_directory", DATABASE_PROFILE,
            "SELECT version_num FROM alembic_version", frozen_sql(operation_id),
        )
        command = (
            'IFS= read -r PGPASSWORD; export PGPASSWORD; '
            'exec psql -XAtq -w -v ON_ERROR_STOP=1 -h 127.0.0.1 -U "$POSTGRES_USER" -d "$1" -c "$2"'
        )
        password = environment["POSTGRES_PASSWORD"]
        if "\n" in password or "\r" in password:
            raise ValueError("Unsupported PostgreSQL password encoding in recovery")
        confirmed = subprocess.run(
            [
                "docker", "--host", f"unix://{SOCKET}", "exec", "--interactive", container,
                "sh", "-ec", command, "dvt-restore-verify", db, ";".join(checks),
            ],
            env=DOCKER_ENV, input=password.encode() + b"\n", stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, check=True, timeout=30,
        )
        if confirmed.stdout.decode().splitlines() != [PG_TARGET, "local", revision, "frozen"]:
            raise ValueError("Restored PostgreSQL did not confirm the source and frozen gate")
        docker("container", "stop", "--timeout=60", container, timeout=70)
    finally:
        docker("container", "rm", "--force", container, check=False, timeout=75)


def restore_data(
    destination: Path, backup: Path, manifest_digest: str, loss_after: str,
    *, source_diagnostics: Path | None = None,
) -> dict:
    import fcntl

    start = time.monotonic()
    destination, backup = safe_path(destination), safe_path(backup)
    if not destination.parent.is_dir() or backup.is_relative_to(destination):
        raise ValueError("Keep the backup outside the new installation directory")
    lock = destination.parent / (".dvt-restore-" + destination.name + ".lock")
    fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    with os.fdopen(fd, "wb") as lock_file:
        info = os.fstat(lock_file.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid or info.st_mode & 0o077:
            raise ValueError("Unsafe restore lock")
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if destination.exists() or destination.is_symlink():
            raise ValueError("Select an absent installation directory on a clean host")
        metadata, plan = inspect_copy(backup)
        if manifest_digest != plan["manifest_digest"] or loss_after != plan["created_at"]:
            raise ValueError("Review the copy digest and separately confirm its exact data loss time")
        check_project(metadata["compose_project"])
        verify_copy_files(backup, metadata)
        with TemporaryDirectory(prefix=".dvt-restore-", dir=destination.parent) as temporary:
            scratch = Path(temporary)
            extract_data(backup / "data.tar.gz", scratch)
            pgdata, image, environment, operation_id, staging = _source(scratch, destination, metadata)
            if source_diagnostics is not None:
                content = read_artifact(safe_path(source_diagnostics), LIMIT)
                if content is None:
                    raise ValueError("The source diagnostics file is missing")
                source_operation = OperationStore.for_host(scratch).get(operation_id)
                value = import_source_failure(content, source_operation)
                write_artifact(staging / "source-failure.json", value.model_dump_json().encode())
            _restore_database(
                backup, pgdata, image, environment, operation_id, metadata["source_revision"],
            )
            verify_copy_files(backup, metadata)
            marker = {
                **plan,
                "elapsed_ms": int((time.monotonic() - start) * 1000),
                "database_and_files_verified": True,
                "admission": "frozen",
            }
            write_artifact(staging / "restored-data.json", canonical_json(marker))
            write_artifact(staging / "restore-input.json", canonical_json({"copy": str(backup)}))
            # The extracted tree never becomes authoritative until checks have all completed.
            os.sync()
            scratch.rename(destination)
            sync_directory(destination.parent)
            return marker


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["plan", "restore-data"])
    parser.add_argument("--copy", required=True, type=Path)
    parser.add_argument("--dir", type=Path)
    parser.add_argument("--confirm-manifest")
    parser.add_argument("--confirm-loss-after")
    parser.add_argument("--source-diagnostics", type=Path)
    args = parser.parse_args()
    try:
        if args.action == "plan":
            metadata, output = inspect_copy(args.copy)
            verify_copy_files(safe_path(args.copy), metadata)
        else:
            if os.geteuid() != 0 or not all(
                (args.dir, args.confirm_manifest, args.confirm_loss_after)
            ):
                raise ValueError("Root, a clean target directory and both confirmations are required")
            output = restore_data(
                args.dir, args.copy, args.confirm_manifest, args.confirm_loss_after,
                source_diagnostics=args.source_diagnostics,
            )
    except (OSError, ValueError, RuntimeError, TypeError, KeyError, subprocess.SubprocessError,
            tarfile.TarError):
        sys.stderr.write("backup: the recovery point or clean restore prerequisites failed verification\n")
        return 1
    sys.stdout.write(json.dumps(output, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
