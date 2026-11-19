"""Run and observe one verified Linux Compose deployment."""

from __future__ import annotations

import json
import re
import subprocess
import time
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path
from uuid import UUID

from ..domain.operation_state import FailureReason
from ..host_bootstrap import docker
from .maintenance_database import frozen_sql
from .maintenance_host import PG_TARGET, ComposeMaintenanceHost
from .staging_docker import StagingDocker, canonical_image_reference, image_references

DATABASE_ID = """
SELECT (pg_control_system()).system_identifier::text || ':' || oid::text
FROM pg_database WHERE datname = current_database()
"""
RECEIPTS = "dvt_release_control.migration_receipts"
# The standalone Gateway migrator takes this bigint advisory key (DVT_MIGR).
MIGRATION_LOCK_ID = 0x4456545F4D494752
MIGRATOR_LOCK = f"""
SELECT EXISTS (
    SELECT FROM pg_locks
    WHERE locktype = 'advisory' AND granted AND objsubid = 1
      AND database = (SELECT oid FROM pg_database WHERE datname = current_database())
      AND classid = {MIGRATION_LOCK_ID >> 32} AND objid = {MIGRATION_LOCK_ID & 0xFFFFFFFF}
)
"""
MANAGED_ROLES = {"gateway", "orchestrator", "project-scheduler", "task-worker", "migrate"}
CONTEXT_ENV = "DVT_MIGRATION_CONTEXT"
MIGRATION_SECONDS = 900
READINESS_SECONDS = 240
POLL_SECONDS = 2


class ApplyError(RuntimeError):
    def __init__(self, reason: FailureReason, message: str) -> None:
        self.reason = reason
        super().__init__(message)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, _req, _fp, _code, _msg, _headers, _newurl):
        return None


def _labels(container: dict) -> dict:
    return container["Config"].get("Labels") or {}


def _env(container: dict) -> dict[str, str]:
    return dict(item.split("=", 1) for item in container["Config"].get("Env") or [] if "=" in item)


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _healthy(container: dict) -> bool:
    state = container["State"]
    return (
        state["Running"]
        and not state["Paused"]
        and not state["Restarting"]
        and (state.get("Health") or {}).get("Status", "healthy") == "healthy"
    )


class ComposeApplicationHost:
    def __init__(self, config: dict, directory: Path, model: dict, plan: dict, deadline) -> None:
        self.config = config
        self.path = directory / "application.compose.yaml"
        self.model = model
        self.plan = plan
        self.platform = plan["platform"]
        self.deadline = deadline
        self.docker = StagingDocker(directory, Path("/root/.docker"))
        self.image_ids: dict[str, str] = {}
        self.services = {name: model["services"][name] for name in plan["services"]}

    def bind_images(self) -> None:
        local_ui = self.config.get("local_ui_image")
        services = self.plan["services"]
        for ref in set(services.values()):
            allow_index = ref == local_ui and ref == services.get("ui")
            if not self.docker.local_image(ref, self.platform, self.deadline, allow_index=allow_index):
                raise ApplyError(FailureReason.INVALID_PACKAGE, "A staged image is unavailable")
            self.image_ids[ref] = self.docker.inspect_image(ref, self.deadline)["Id"]

    def up(self, service: str | None = None, *, path: Path | None = None) -> bool:
        args = [
            "compose",
            "--project-name",
            self.config["project"],
            "--project-directory",
            self.config["data"],
            "--env-file",
            "/dev/null",
            "--file",
            str(path or self.path),
        ]
        for profile in self.plan["profiles"]:
            args.extend(("--profile", profile))
        args.extend(("up", "--detach", "--pull", "never", "--no-build"))
        if service is None:
            args.append("--remove-orphans")
        else:
            args.append(service)
        try:
            return docker(*args, check=False, timeout=100).returncode == 0
        except subprocess.TimeoutExpired:
            # Docker may already be starting some containers. Observe instead of guessing.
            return False

    def containers(self) -> dict[str, list[dict]]:
        output = docker(
            "container",
            "ls",
            "--all",
            "--quiet",
            "--no-trunc",
            "--filter",
            f"label=com.docker.compose.project={self.config['project']}",
        ).stdout.split()
        results: dict[str, list[dict]] = defaultdict(list)
        for container in (
            json.loads(docker("container", "inspect", *output).stdout) if output else []
        ):
            labels = _labels(container)
            role = labels.get("com.docker.compose.service")
            allowed = {self.plan["services"].get(role), self.plan["observed_images"].get(role)}
            if role == "installation_manager":
                allowed.update((self.config["manager"], self.config["candidate"]))
            if role == "migrate" and not container["State"]["Running"]:
                allowed.add(self.plan["observed_images"].get("gateway"))
            allowed.discard(None)
            if (
                labels.get("com.docker.compose.project") != self.config["project"]
                or labels.get("com.docker.compose.oneoff", "").lower() != "false"
                or not allowed
            ):
                raise ApplyError(
                    FailureReason.COMPOSE, "Unexpected container in the staged project"
                )
            if container["Image"] not in {self.image_ids.get(ref) for ref in allowed}:
                (image,) = json.loads(docker("image", "inspect", container["Image"]).stdout)
                expected_references = {canonical_image_reference(ref) for ref in allowed}
                if not (expected_references & image_references(image)):
                    raise ApplyError(
                        FailureReason.COMPOSE, "A container is outside the staged images"
                    )
            results[role].append(container)
        if any(len(items) > 1 for role, items in results.items() if role != "task-worker"):
            raise ApplyError(FailureReason.COMPOSE, "A service has unexpected replicas")
        return results

    def is_target(self, role: str, container: dict) -> bool:
        return container["Image"] == self.image_ids[self.plan["services"][role]]

    def postgres(self, rows: dict[str, list[dict]]) -> str:
        (pg,) = rows.get("postgres", ())
        mounted = {
            (mount["Source"], mount["Destination"], mount["Type"], mount["RW"])
            for mount in pg["Mounts"]
        }
        planned = {
            (mount["source"], mount["target"], mount["type"], not mount.get("read_only", False))
            for mount in self.services["postgres"]["volumes"]
        }
        if (
            not self.is_target("postgres", pg)
            or not _healthy(pg)
            or mounted != planned
            or pg["HostConfig"].get("PortBindings")
            or not any(dst == PG_TARGET for _, dst, _, _ in mounted)
            or any(
                _env(pg).get(key) != val
                for key, val in self.services["postgres"]["environment"].items()
                if key in {"POSTGRES_USER", "POSTGRES_DB", "POSTGRES_PASSWORD", "PGDATA"}
            )
        ):
            raise ApplyError(
                FailureReason.DATABASE_UNAVAILABLE, "PostgreSQL differs from the verified plan"
            )
        if self.sql(pg["Id"], "SHOW data_directory") != PG_TARGET:
            raise ApplyError(FailureReason.DATABASE_UNAVAILABLE, "PostgreSQL uses unexpected data")
        return pg["Id"]

    @staticmethod
    def sql(pg: str, query: str) -> str:
        return ComposeMaintenanceHost.sql(pg, query)

    def database_identity(self, pg: str) -> str:
        value = self.sql(pg, DATABASE_ID)
        if not re.fullmatch(r"[0-9]+:[0-9]+", value):
            raise ApplyError(
                FailureReason.DATABASE_UNAVAILABLE, "PostgreSQL identity is unavailable"
            )
        return value

    def wait_for_database(self) -> str:
        stop = time.monotonic() + 75
        while time.monotonic() < stop:
            rows = self.containers()
            if rows.get("postgres") and _healthy(rows["postgres"][0]):
                return self.postgres(rows)
            time.sleep(POLL_SECONDS)
        raise ApplyError(FailureReason.DATABASE_UNAVAILABLE, "PostgreSQL did not become ready")

    @staticmethod
    def receipt_where(context: str) -> str:
        values = json.loads(context)
        operation = UUID(values["operation"])
        return f"operation_id = '{operation}' AND context = {_literal(context)}::jsonb"

    def phase(self, pg: str, context: str) -> str | None:
        if self.database_identity(pg) != json.loads(context)["database"]:
            raise ApplyError(
                FailureReason.INCOMPATIBLE_SCHEMA, "The operation belongs to another database"
            )
        if self.sql(pg, f"SELECT to_regclass('{RECEIPTS}')") != RECEIPTS:
            return None
        phase = self.sql(pg, f"SELECT phase FROM {RECEIPTS} WHERE {self.receipt_where(context)}")
        return phase or None

    def migration_locked(self, pg: str) -> bool:
        result = self.sql(pg, MIGRATOR_LOCK)
        if result not in {"t", "f"}:
            raise ApplyError(FailureReason.DATABASE_UNAVAILABLE, "Cannot observe the migrator lock")
        return result == "t"

    def revision(self, pg: str) -> str | None:
        if not self.sql(pg, "SELECT to_regclass('alembic_version')"):
            return None
        value = self.sql(pg, "SELECT version_num FROM alembic_version")
        if not value:
            return None
        if not re.fullmatch(r"[0-9a-f]{4,32}", value):
            raise ApplyError(
                FailureReason.INCOMPATIBLE_SCHEMA, "Unexpected database schema revisions"
            )
        return value

    def migration_done(self, pg: str, rows: dict[str, list[dict]], context: str) -> bool:
        phase = self.phase(pg, context)
        values = json.loads(context)
        if phase in {"done", "resumed"} and self.revision(pg) != values["target"]:
            raise ApplyError(
                FailureReason.INCOMPATIBLE_SCHEMA, "Receipt and actual database revision disagree"
            )
        if (
            phase == "done"
            and values["source"] is not None
            and self.sql(pg, frozen_sql(UUID(values["operation"]))) != "frozen"
        ):
            raise ApplyError(FailureReason.INCOMPATIBLE_SCHEMA, "The update lost its frozen gate")
        if not rows.get("migrate"):
            return False
        (container,) = rows["migrate"]
        if (
            not self.is_target("migrate", container)
            or _env(container).get(CONTEXT_ENV) != context
            or container["HostConfig"]["RestartPolicy"]["Name"] not in {"", "no"}
        ):
            if container["State"]["Running"]:
                raise ApplyError(FailureReason.MIGRATION, "Another migrator is still running")
            return False
        state = container["State"]
        return (
            state["Status"] == "exited" and state["ExitCode"] == 0 and phase in {"done", "resumed"}
        )

    def wait_for_migration(self, pg: str, context: str) -> None:
        stop = time.monotonic() + MIGRATION_SECONDS
        while time.monotonic() < stop:
            rows = self.containers()
            if self.migration_done(pg, rows, context):
                return
            if rows.get("migrate"):
                (previous,) = rows["migrate"]
                if _env(previous).get(CONTEXT_ENV) == context and previous["State"]["Status"] in {
                    "exited",
                    "dead",
                }:
                    break
            time.sleep(POLL_SECONDS)
        raise ApplyError(FailureReason.MIGRATION, "The one-shot migrator did not confirm success")

    def app_ready(
        self, pg: str, context: str | None, operation_id: UUID | None, origin: str, worker_count: int
    ) -> bool:
        rows = self.containers()
        if set(rows) != set(self.services):
            return False
        if context is not None:
            if not self.migration_done(pg, rows, context):
                return False
        else:
            (migrate,) = rows["migrate"]
            state = migrate["State"]
            if state["Status"] != "exited" or state["ExitCode"] != 0:
                return False
        for role, containers in rows.items():
            expected_count = worker_count if role == "task-worker" else 1
            if len(containers) != expected_count or any(
                not self.is_target(role, container)
                or (role != "migrate" and not _healthy(container))
                or (role in MANAGED_ROLES and (_env(container).get(CONTEXT_ENV) or None) != context)
                for container in containers
            ):
                return False

        workers = {c["Config"]["Hostname"] for c in rows["task-worker"]}
        if (
            len(workers) != worker_count
            or docker(
                "exec",
                rows["gateway"][0]["Id"],
                "python3",
                "-m",
                "services.gateway.deployment_probe",
                *sorted(workers),
                check=False,
                timeout=15,
            ).returncode
        ):
            return False

        return self._public_ready(operation_id, origin)

    def _public_ready(self, operation_id: UUID | None, origin: str) -> bool:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
        headers = {"X-DVT-Deployment": str(operation_id)} if operation_id is not None else {}
        health = urllib.request.Request(f"{origin}/api/health", headers=headers)
        try:
            with opener.open(health, timeout=4) as response:
                if response.status != 200 or json.loads(response.read(4096)) != {"status": "ok"}:
                    return False
            with opener.open(f"{origin}/", timeout=4) as response:
                if response.status != 200 or "text/html" not in response.headers.get(
                    "Content-Type", ""
                ):
                    return False
            try:
                with opener.open(f"{origin}/mcp", timeout=4):
                    return False
            except urllib.error.HTTPError as error:
                with error:
                    return (
                        error.code == 401
                        and json.loads(error.read(4096))["error"]["code"] == "AUTH_INVALID"
                        if "dvt-ai-mcp" in self.services
                        else error.code == 404
                    )
        except (OSError, ValueError, KeyError, TypeError):
            return False

    def wait_for_application(
        self, pg: str, context: str | None, operation_id: UUID | None, origin: str, count: int
    ) -> bool:
        stop = time.monotonic() + READINESS_SECONDS
        consecutive = 0
        while time.monotonic() < stop:
            consecutive = (
                consecutive + 1 if self.app_ready(pg, context, operation_id, origin, count) else 0
            )
            if consecutive == 2:
                return True
            time.sleep(POLL_SECONDS)
        return False

    def retire_stopped_services(self) -> None:
        rows = self.containers()
        for role in self.plan["retire"]:
            for container in rows.get(role, ()):
                if (
                    role in self.services
                    or container["State"]["Running"]
                    or container["HostConfig"]["RestartPolicy"]["Name"] not in {"", "no"}
                ):
                    raise ApplyError(
                        FailureReason.COMPOSE, "A service approved for retirement is active"
                    )
                docker("container", "rm", container["Id"])

    def restore_restart_policy(self) -> None:
        for role, rows in self.containers().items():
            if role == "migrate":
                continue
            policy = self.services[role].get("restart", "no")
            for container in rows:
                current = container["HostConfig"]["RestartPolicy"]["Name"] or "no"
                if policy != current:
                    docker("container", "update", f"--restart={policy}", container["Id"])

    def resume(self, pg: str, context: str) -> bool:
        data = json.loads(context)
        operation = UUID(data["operation"])
        where = self.receipt_where(context)
        # The gate and the completion marker commit together. An already-open gate
        # is never treated as success without this operation's release marker.
        if data["source"] is None:
            self.sql(
                pg, f"UPDATE {RECEIPTS} SET phase = 'resumed' WHERE {where} AND phase = 'done'"
            )
        else:
            self.sql(
                pg,
                f"""
                WITH ready AS (
                    SELECT operation_id FROM {RECEIPTS}
                    WHERE {where} AND phase = 'done' FOR UPDATE
                ), opened AS (
                    UPDATE task_admission_control SET operation_id = NULL, frozen = false
                    WHERE singleton = 1 AND frozen AND operation_id = '{operation}'
                      AND EXISTS (SELECT 1 FROM ready)
                    RETURNING singleton
                )
                UPDATE {RECEIPTS} SET phase = 'resumed'
                WHERE {where} AND phase = 'done' AND EXISTS (SELECT 1 FROM opened)
            """,
            )
            if (
                self.sql(
                    pg,
                    """
                SELECT 'open' FROM task_admission_control
                WHERE singleton = 1 AND operation_id IS NULL AND NOT frozen
            """,
                )
                != "open"
            ):
                return False
        return self.phase(pg, context) == "resumed"
