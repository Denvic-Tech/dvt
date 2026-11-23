"""Quiesce the supported Linux Compose topology without stopping its web manager."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import BinaryIO
from uuid import UUID

from ..domain.operation_state import ArtifactKind
from ..domain.release_manifest import strict_json
from ..host_bootstrap import CONTROL, DOCKER_ENV, SOCKET, check_image, container_name, docker
from .maintenance_database import DATABASE_PROFILE, NO_OTHER_CONNECTIONS, frozen_sql
from .operation_store import OperationStore
from .staging_artifacts import read_artifact
from .staging_docker import image_references

PG_TARGET = "/var/lib/postgresql/data"
CORE_SERVICES = {
    "gateway", "orchestrator", "project-scheduler", "task-worker",
    "installation_manager", "postgres", "valkey",
}
KEEP_RUNNING = {"installation_manager", "postgres"}
GATE_PARTICIPANTS = {"gateway", "orchestrator", "project-scheduler", "task-worker"}


class MaintenancePrerequisite(ValueError):
    """The source cannot safely take part in this maintenance protocol."""


def _labels(container: dict) -> dict:
    return container["Config"].get("Labels") or {}


def _role(container: dict) -> str | None:
    return _labels(container).get("com.docker.compose.service")


def _networks(container: dict) -> set[str]:
    return set(container["NetworkSettings"].get("Networks") or {})


def _environment(container: dict) -> dict[str, str]:
    return dict(item.split("=", 1) for item in container["Config"].get("Env") or [] if "=" in item)


def _running(container: dict) -> bool:
    return container["State"]["Running"]


def _inspect(*ids: str) -> list[dict]:
    return json.loads(docker("container", "inspect", *ids).stdout) if ids else []


class ComposeMaintenanceHost:
    def __init__(self, config: dict, operation_id: UUID, source_images: dict[str, str]) -> None:
        self.config = config
        self.operation_id = operation_id
        self.source_images = source_images
        self.data = Path(config["data"])
        self.pgdata: Path | None = None

    def _project(self) -> list[dict]:
        ids = docker(
            "container", "ls", "--all", "--quiet", "--filter",
            f"label=com.docker.compose.project={self.config['project']}",
        ).stdout.split()
        containers = _inspect(*ids)
        if any(
            _labels(c).get("com.docker.compose.oneoff", "").lower() == "true"
            or _role(c) not in {*self.source_images, "migrate"}
            or (_role(c) == "migrate" and (
                _running(c) or c["HostConfig"]["RestartPolicy"]["Name"] not in ("", "no")
            ))
            for c in containers
        ):
            raise MaintenancePrerequisite("Unknown or active one-off container in the project")
        return [c for c in containers if _role(c) != "migrate"]

    def _is_route_executor(self, container: dict) -> bool:
        labels = _labels(container)
        if (
            labels.get("dvt.executor.instance") != self.config["instance"]
            or container["Name"] != "/" + container_name(self.config)
            or container["Image"] != check_image(self.config["executor"])
        ):
            return False
        try:
            launched_step = UUID(labels["dvt.executor.operation"])
        except (KeyError, ValueError):
            return False
        if launched_step == self.operation_id:
            return True
        store = OperationStore.for_host(self.data)
        if store.get(launched_step) is None:
            return False
        return store.route_root(launched_step) == store.route_root(self.operation_id)

    def _is_legacy_supervisor(self, container: dict) -> bool:
        label = _labels(container).get("tech.denvic.legacy-bridge.handoff")
        if (
            not label
            or container["Name"] != f"/dvt-legacy-handoff-{label}"
            or container["HostConfig"]["NetworkMode"] != "host"
            or container["Image"] != check_image(self.config["executor"])
        ):
            return False
        store = OperationStore.for_host(self.data)
        root = store.route_root(self.operation_id)
        staging = store.artifact_path(ArtifactKind.STAGING, root)
        content = read_artifact(staging / "legacy-import.json", 256 * 1024)
        if content is None:
            return False
        job_id = strict_json(content)["legacy_job_id"]
        expected = hashlib.sha256(f"{self.config['project']}/{job_id}".encode()).hexdigest()[:24]
        return label == expected

    def _verify_scope(self, containers: list[dict]) -> dict:
        roles = {_role(c) for c in containers}
        if roles != set(self.source_images) or not roles >= CORE_SERVICES:
            raise MaintenancePrerequisite("The Compose service set differs from the prepared plan")
        if len(containers) != len(roles) + sum(_role(c) == "task-worker" for c in containers) - 1:
            raise MaintenancePrerequisite("Only task-worker may have service replicas")
        for c in containers:
            role = _role(c)
            (image,) = json.loads(docker("image", "inspect", c["Image"]).stdout)
            if self.source_images[role] not in image_references(image):
                raise MaintenancePrerequisite("A running image differs from the prepared source")
            # Compose labels and environment cannot assert support; check the pinned image.
            if (
                role in GATE_PARTICIPANTS
                and (image.get("Config", {}).get("Labels") or {}).get("tech.denvic.task-admission") != "1"
            ):
                raise MaintenancePrerequisite("A source service does not support task admission v1")
            if c["State"]["Paused"] or c["State"]["Restarting"]:
                raise MaintenancePrerequisite("A container is paused or restarting")
            for m in c["Mounts"]:
                source = Path(m["Source"]).resolve()
                if (
                    role == "installation_manager"
                    and m["Destination"] == SOCKET
                    and m["Source"] == SOCKET
                    and m["Type"] == "bind"
                ):
                    continue
                if m["Type"] != "bind" or not source.is_relative_to(self.data):
                    raise MaintenancePrerequisite(
                        "This profile requires all persistent storage inside the DVT data directory"
                    )
                if source != Path(m["Source"]):
                    raise MaintenancePrerequisite("A persistent mount changed through a symlink")
        (manager,) = [c for c in containers if _role(c) == "installation_manager"]
        current = read_artifact(self.data / CONTROL / "current-manager", 512)
        approved = {self.config["manager"], self.config["candidate"]}
        if current is not None:
            approved.add(current.decode())
        if (
            self.source_images["installation_manager"] not in approved
            or manager["Config"]["Cmd"] != ["candidate-web", str(self.data)]
            or not _running(manager)
        ):
            raise MaintenancePrerequisite("The web manager must use the protected candidate mode")
        (database,) = [c for c in containers if _role(c) == "postgres"]
        mounts = [
            m for m in database["Mounts"] if m["Destination"] == PG_TARGET and m["RW"]
        ]
        if (
            len(mounts) != 1
            or len(database["Mounts"]) != 1
            or database["HostConfig"].get("PortBindings")
            or database["HostConfig"]["NetworkMode"] in ("host", "none", "bridge")
            or not _running(database)
            or not _networks(database)
        ):
            raise MaintenancePrerequisite("PostgreSQL is not a private local Compose database")
        db_env = _environment(database)
        for client in containers:
            if _role(client) not in GATE_PARTICIPANTS:
                continue
            client_env = _environment(client)
            shared_networks = _networks(database) & _networks(client)
            aliases = {
                alias
                for network in shared_networks
                for alias in database["NetworkSettings"]["Networks"][network].get("Aliases") or []
            }
            if (
                not all(db_env.get(key) for key in ("POSTGRES_USER", "POSTGRES_DB"))
                or any(
                    client_env.get(key) != db_env.get(key)
                    for key in ("POSTGRES_USER", "POSTGRES_DB", "POSTGRES_PASSWORD")
                )
                or client_env.get("POSTGRES_PORT", "5432") != "5432"
                or client_env.get("POSTGRES_HOST") not in aliases
            ):
                raise MaintenancePrerequisite("A source writer uses a different PostgreSQL database")

        self.pgdata = Path(mounts[0]["Source"])
        if self.pgdata == self.data:
            raise MaintenancePrerequisite("PostgreSQL must have a dedicated data subdirectory")

        # Detect other containers that can write a persistent bind or use the private DB network.
        allowed = {c["Id"] for c in containers}
        outsiders = docker("container", "ls", "--quiet", "--no-trunc").stdout.split()
        for c in _inspect(*(cid for cid in outsiders if cid not in allowed)):
            if self._is_route_executor(c) or self._is_legacy_supervisor(c):
                continue
            if _networks(c) & _networks(database):
                raise MaintenancePrerequisite("Another container shares the PostgreSQL network")
            for mount in c["Mounts"]:
                source = Path(mount["Source"]).resolve()
                if mount["RW"] and (
                    source.is_relative_to(self.data) or self.data.is_relative_to(source)
                ):
                    raise MaintenancePrerequisite("Another container can write the DVT files")
        return database

    def capture(self, revision: str) -> list[dict]:
        containers = self._project()
        database = self._verify_scope(containers)
        if not all(_running(c) for c in containers if _role(c) != "task-worker"):
            raise MaintenancePrerequisite("The prepared application is not fully running")
        if not any(_role(c) == "task-worker" and _running(c) for c in containers):
            raise MaintenancePrerequisite("No running worker is available to drain the queue")
        self._check_database(database["Id"], revision)
        return sorted(
            (
                {
                    "id": c["Id"],
                    "role": _role(c),
                    "image": c["Image"],
                    "running": _running(c),
                    "restart": c["HostConfig"]["RestartPolicy"],
                }
                for c in containers
            ),
            key=lambda item: item["id"],
        )

    def validate(self, expected: list[dict], revision: str) -> str:
        containers = self._project()
        database = self._verify_scope(containers)
        if {(c["Id"], _role(c), c["Image"]) for c in containers} != {
            (c["id"], c["role"], c["image"]) for c in expected
        }:
            raise MaintenancePrerequisite("The recorded source containers changed")
        self._check_database(database["Id"], revision)
        return database["Id"]

    def _check_database(self, container_id: str, revision: str) -> None:
        if (
            self.sql(container_id, "SHOW data_directory") != PG_TARGET
            or self.sql(container_id, DATABASE_PROFILE) != "local"
            or self.sql(container_id, "SELECT version_num FROM alembic_version") != revision
        ):
            raise MaintenancePrerequisite("The database layout or schema differs from the plan")
        if self.sql(container_id, "SELECT singleton FROM task_admission_control") != "1":
            raise MaintenancePrerequisite("This schema does not provide the admission gate")

    def stop_writers(self, expected: list[dict]) -> None:
        ids = [c["id"] for c in expected if c["role"] not in KEEP_RUNNING]
        # Disable Docker auto-restart before stopping. The initial settings are durable.
        docker("container", "update", "--restart=no", *ids)
        running = [c["Id"] for c in _inspect(*ids) if _running(c)]
        if running:
            docker("container", "stop", "--timeout=30", *running, timeout=120)

    def assert_frozen(self, expected: list[dict], revision: str) -> str:
        pg = self.validate(expected, revision)
        ids = [c["id"] for c in expected if c["role"] not in KEEP_RUNNING]
        if any(
            _running(c) or c["HostConfig"]["RestartPolicy"]["Name"] != "no"
            for c in _inspect(*ids)
        ):
            raise MaintenancePrerequisite("A previous application writer is still active")
        if (
            self.sql(pg, frozen_sql(self.operation_id)) != "frozen"
            or self.sql(pg, NO_OTHER_CONNECTIONS) != "exclusive"
        ):
            raise MaintenancePrerequisite("Database admission is not sealed or other clients exist")
        return pg

    @staticmethod
    def sql(container_id: str, query: str) -> str:
        # Docker socket access is host privileged. The existing DB password stays
        # in the PostgreSQL container and never becomes an argument or journal field.
        result = docker(
            "exec", container_id, "sh", "-ec",
            'export PGPASSWORD="${POSTGRES_PASSWORD:-}" '
            'PGOPTIONS="-c lock_timeout=5000 -c statement_timeout=20000"; '
            'exec psql -XAtq -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "$1"',
            "dvt-maintenance-sql", query, timeout=35,
        )
        return result.stdout.strip()

    @staticmethod
    def postgres_tool(
        container_id: str, action: str, stream: BinaryIO, *, verify: bool = False
    ) -> None:
        prologue = 'export PGPASSWORD="${POSTGRES_PASSWORD:-}"; '
        scripts = {
            "database.dump": (
                'pg_restore --file=/dev/null' if verify
                else prologue + 'pg_dump -Fc -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
            ),
            "globals.sql": prologue + 'pg_dumpall --globals-only -U "$POSTGRES_USER"',
        }
        stdin = stream if verify else subprocess.DEVNULL
        stdout = subprocess.DEVNULL if verify else stream
        args = ["docker", "--host", f"unix://{SOCKET}", "exec"]
        if verify:
            args.append("-i")
        args.extend((container_id, "sh", "-ec", f"exec {scripts[action]}"))
        if not verify:
            # The prologue is itself a shell statement, not an argv command.
            args[-1] = scripts[action]
        subprocess.run(
            args, env=DOCKER_ENV, stdin=stdin, stdout=stdout,
            stderr=subprocess.DEVNULL, timeout=3600, check=True,
        )
