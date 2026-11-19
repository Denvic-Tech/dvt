"""Start and verify the previous pinned application on a recovered physical database."""

from __future__ import annotations

import argparse
import contextlib
import getpass
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

from ..domain.operation_state import (
    ArtifactKind,
    Checkpoint,
    CheckpointOutcome,
    FailureReason,
    Observation,
    OperationStage,
    OwnershipConflict,
)
from ..domain.release_manifest import canonical_json, digest_of, strict_json
from ..host_bootstrap import (
    CONTROL,
    DOCKER_ENV,
    SOCKET,
    atomic_write,
    init_container,
    load_host,
    manager_origin,
    safe_path,
)
from ..infrastructure.application_host import (
    CONTEXT_ENV,
    MANAGED_ROLES,
    MIGRATION_LOCK_ID,
    RECEIPTS,
    ApplyError,
    ComposeApplicationHost,
    _literal,
)
from ..infrastructure.maintenance_archive import verify_copy_files
from ..infrastructure.maintenance_database import frozen_sql
from ..infrastructure.operation_files import _require_regular_file
from ..infrastructure.operation_store import FORMAT_VERSION, OperationStore
from ..infrastructure.operator_wiring import operator_binds
from ..infrastructure.staging_artifacts import artifact_directory, read_artifact, write_artifact
from ..infrastructure.staging_commands import Deadline, RetryPolicy
from ..infrastructure.staging_compose import COMPOSE_LIMIT
from ..infrastructure.staging_docker import _compose_value
from .application_apply import LIMIT, _artifact, _compose_literal, _validate_runtime
from .portable_restore import inspect_copy

STAGES = {
    OperationStage.BACKUP, OperationStage.RECOVERY_REQUIRED, OperationStage.RECOVERING,
    OperationStage.VERIFYING, OperationStage.RESUMING,
}
AUTHORIZATION = "restore-authorization.json"
FINAL_PROOF = "restore-proof.json"
ACCESS_COOKIE = re.compile(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")
AUTH_PROBE = """
import asyncio, json, sys, urllib.request
port, project = sys.argv[1:3]
proof = json.loads(sys.stdin.read(32 * 1024))
token = proof['access_token']

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args):
        return None

opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

headers = {'Cookie': 'access_token=' + token}
request = urllib.request.Request('http://127.0.0.1:' + port + '/api/user/info', headers=headers)
with opener.open(request, timeout=6) as response:
    user = json.loads(response.read(2 * 1024 * 1024))
if str(user.get('role', '')).lower() not in {'admin', 'superadmin'}:
    sys.exit(1)

async def verify_project_and_extensions():
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from services.gateway.auth_app import create_auth_app
    from services.gateway.routes.extensions import list_extensions
    from services.gateway.routes.project.crud import get_project_by_id, get_projects

    # Initialize the same auth dependencies without starting Gateway lifespan.
    # Only these read-only routes run in this private process, without a listener.
    create_auth_app()
    app = FastAPI(openapi_url=None)
    app.add_api_route('/projects/{project_id}', get_project_by_id, methods=['GET'])
    app.add_api_route('/projects', get_projects, methods=['GET'])
    app.add_api_route('/extensions', list_extensions, methods=['GET'])
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url='http://localhost', headers=headers,
    ) as client:
        if project:
            project_response = await client.get('/projects/' + project)
            if project_response.raise_for_status().json().get('id') != project:
                return False
        elif (await client.get('/projects', params={'limit': 1})).raise_for_status().json():
            return False
        extensions = (await client.get('/extensions')).raise_for_status().json()
        installed = sorted(e['name'] for e in extensions if e.get('is_installed'))
        return installed == sorted(proof['extensions'])

if not asyncio.run(verify_project_and_extensions()):
    sys.exit(1)
"""


def _validate_restored_runtime(services: dict, networks: dict, config: dict) -> None:
    gateway = services["gateway"]
    sources = operator_binds(config["data"], http=config.get("manager_http") is True)
    volumes = gateway.get("volumes", [])
    bridge = [mount for mount in volumes if mount["target"] in sources]
    origin = gateway.get("environment", {}).get("DVT_OPERATOR_MANAGER_ORIGIN")
    if not bridge and origin is None:
        _validate_runtime({"services": services})
        return

    default_network = {"name": f"{config['project']}_default"}
    if (
        origin != manager_origin(config)
        or services["installation_manager"].get("networks") != {"default": None}
        or networks.get("default") not in (default_network, {**default_network, "ipam": {}})
        or gateway.get("networks") != {"dvt-net": None, "default": None}
        or services["migrate"].get("networks") != {"dvt-net": None}
        or {mount["target"] for mount in bridge} != sources.keys()
        or len(bridge) != len(sources)
    ):
        raise ApplyError(FailureReason.COMPOSE, "The restored Gateway operator wiring is invalid")

    try:
        safe_path(Path(config["data"]) / CONTROL)
        for mount in bridge:
            target = mount["target"]
            source = sources[target]
            if (
                mount != {
                    "type": "bind", "source": source, "target": target,
                    "read_only": True, "bind": {"create_host_path": False},
                }
                or mount["read_only"] is not True
                or mount["bind"]["create_host_path"] is not False
            ):
                raise ValueError("Unexpected protected bind")
            _require_regular_file(Path(source).lstat())
    except (OSError, ValueError) as error:
        raise ApplyError(
            FailureReason.COMPOSE, "The restored Gateway operator binds are invalid",
        ) from error

    # Compare the original roles using a temporary view. Docker receives the
    # recovered model, including the verified mounts and the manager network.
    base_gateway = {
        **gateway,
        "volumes": [mount for mount in volumes if mount["target"] not in sources],
        "networks": {"dvt-net": gateway["networks"]["dvt-net"]},
    }
    _validate_runtime({"services": {**services, "gateway": base_gateway}})


@dataclass(frozen=True)
class FunctionalProof:
    access_cookie: str = field(repr=False)
    project: UUID | None


@dataclass(frozen=True)
class RestoreRuntime:
    store: OperationStore
    config: dict
    probe_manager: Callable[[dict, OperationStore, UUID, UUID], None]

    def execute(self, operation_id: UUID, *, authorize=False, proof: FunctionalProof | None = None):
        with contextlib.suppress(OwnershipConflict), self.store.claim(operation_id) as owner:
            operation = self.store.get(operation_id)
            stage = operation.stage
            if stage not in STAGES:
                return operation.stage is OperationStage.SUCCEEDED
            reason = FailureReason.BACKUP
            try:
                directory = artifact_directory(self.store, ArtifactKind.STAGING, operation_id)
                marker, prior, model = self._prepare(operation, directory)
                if authorize:
                    write_artifact(
                        directory / AUTHORIZATION,
                        canonical_json({"backup_digest": marker["manifest_digest"]}),
                    )
                intent = read_artifact(directory / AUTHORIZATION, LIMIT)
                if intent is None:
                    return False
                if strict_json(intent) != {"backup_digest": marker["manifest_digest"]}:
                    raise ValueError("The restore authorization refers to a different copy")

                if stage is OperationStage.BACKUP:
                    owner.checkpoint(Checkpoint(
                        OperationStage.BACKUP, CheckpointOutcome.VERIFIED,
                        observation=Observation(backup_id=operation.id),
                    ))
                    owner.checkpoint(Checkpoint(OperationStage.RECOVERY_REQUIRED))
                    stage = OperationStage.RECOVERY_REQUIRED
                if stage is OperationStage.RECOVERY_REQUIRED:
                    owner.checkpoint(Checkpoint(OperationStage.RECOVERING))
                    stage = OperationStage.RECOVERING

                reason = FailureReason.INCOMPATIBLE_RELEASE
                deadline = Deadline(RetryPolicy(), Path(self.config["temporary"]))
                host = ComposeApplicationHost(self.config, directory, model, {
                    "services": prior["images"], "observed_images": prior["images"],
                    "profiles": prior["profiles"], "platform": "linux/amd64", "retire": [],
                }, deadline)
                host.bind_images()
                _validate_restored_runtime(host.services, model.get("networks", {}), self.config)
                origin = self.store.identity().public_url
                worker = host.services["task-worker"]
                count = (worker.get("deploy") or {}).get("replicas", worker.get("scale", 1))

                reason = FailureReason.DATABASE_UNAVAILABLE
                host.containers()  # Verify any existing containers before the first Compose call.
                bootstrap = directory / "restore-postgres.compose.yaml"
                write_artifact(bootstrap, canonical_json(_compose_literal(model)))
                if not host.containers().get("postgres"):
                    host.up("postgres", path=bootstrap)
                pg = host.wait_for_database()

                reason = FailureReason.INCOMPATIBLE_SCHEMA
                context = self._receipt(host, pg, operation, prior, stage)
                for role in MANAGED_ROLES:
                    host.services[role]["environment"][CONTEXT_ENV] = context
                compose = canonical_json(_compose_literal(model))
                write_artifact(host.path, compose)

                reason = FailureReason.MANAGER_UNAVAILABLE
                manager_image = host.services["installation_manager"]["image"]
                if init_container({**self.config, "manager": manager_image}, "candidate-inspect") != str(
                    FORMAT_VERSION
                ):
                    raise ApplyError(reason, "The saved manager cannot read the restored journal")
                if not host.containers().get("installation_manager"):
                    host.up("installation_manager")
                self.probe_manager(self.config, self.store, operation.id, owner.record.claim_id)

                reason = FailureReason.GATEWAY_UNAVAILABLE
                if not host.app_ready(pg, context, operation.id, origin, count):
                    host.up()
                if not host.wait_for_application(pg, context, operation.id, origin, count):
                    raise ApplyError(reason, "The restored roles did not become ready")
                self.probe_manager(self.config, self.store, operation.id, owner.record.claim_id)
                if stage is OperationStage.RECOVERING:
                    owner.checkpoint(Checkpoint(
                        OperationStage.VERIFYING, CheckpointOutcome.VERIFIED,
                        observation=Observation(observed_revision=prior["revision"]),
                    ))
                    stage = OperationStage.VERIFYING

                trusted_proof = {
                    "context_digest": digest_of(context.encode()),
                    "backup_digest": marker["manifest_digest"],
                    "application_auth_verified": True,
                    "project_and_extensions_verified": True,
                }
                proof_path = directory / FINAL_PROOF
                if stage is OperationStage.VERIFYING:
                    if proof is None:
                        return True  # Ready to verify with a fresh app session. Admission stays frozen.
                    reason = FailureReason.GATEWAY_UNAVAILABLE
                    if host.sql(pg, frozen_sql(operation.id)) != "frozen":
                        raise ApplyError(reason, "The restored task gate is not frozen")
                    self._verify_application(host, pg, proof)
                    write_artifact(proof_path, canonical_json(trusted_proof))
                    owner.checkpoint(Checkpoint(OperationStage.RESUMING, CheckpointOutcome.VERIFIED))
                    stage = OperationStage.RESUMING
                if strict_json(_artifact(proof_path)) != trusted_proof:
                    raise ValueError("The restored application proof is missing or outdated")

                reason = FailureReason.COMPOSE
                data = Path(self.config["data"])
                atomic_write(data / "docker-compose.yaml", compose)
                atomic_write(data / CONTROL / "current-manager", manager_image.encode())
                atomic_write(data / CONTROL / "current-release.json", canonical_json({
                    **prior,
                    "authorized_operation": prior.get("authorized_operation", prior["operation"]),
                    "operation": str(operation.id),
                    "database": host.database_identity(pg),
                    "compose_digest": digest_of(compose),
                }))
                reason = FailureReason.DATABASE_UNAVAILABLE
                if not host.resume(pg, context):
                    raise ApplyError(reason, "Recovery did not confirm the reopened gate")
                owner.checkpoint(Checkpoint(
                    OperationStage.SUCCEEDED, CheckpointOutcome.VERIFIED,
                    observation=Observation(
                        observed_revision=prior["revision"],
                        observed_digest=prior["images"]["gateway"].rsplit("@", 1)[-1],
                    ),
                ))
            except (
                OSError, ValueError, RuntimeError, TypeError, KeyError, subprocess.SubprocessError,
            ) as exc:
                if isinstance(exc, ApplyError):
                    reason = exc.reason
                owner.checkpoint(Checkpoint(stage, CheckpointOutcome.RETRYABLE_ERROR, reason))
                return False
            else:
                return True
        return False

    def _prepare(self, operation, directory: Path):
        data = Path(self.config["data"])
        marker = strict_json(_artifact(directory / "restored-data.json"))
        selected = strict_json(_artifact(directory / "restore-input.json"))
        copy = safe_path(selected["copy"])
        metadata, plan = inspect_copy(copy)
        if (
            plan != {key: marker[key] for key in plan}
            or metadata["instance_id"] != str(operation.instance_id)
            or metadata["backup_id"] != str(operation.id)
            or metadata["source_revision"] != operation.observation.source_revision
            or metadata["source_digest"] != operation.observation.source_digest
            or marker["admission"] != "frozen"
        ):
            raise ValueError("The copied recovery point does not match the operation")
        verify_copy_files(copy, metadata)
        pointer = directory / "restore-source.json"
        source_compose = directory / "restore-source.compose.yaml"
        if read_artifact(pointer, LIMIT) is None:
            current = _artifact(data / CONTROL / "current-release.json")
            compose = _artifact(data / "docker-compose.yaml", 8 * COMPOSE_LIMIT)
            write_artifact(source_compose, compose)
            write_artifact(pointer, current)
        else:
            current = _artifact(pointer)
            compose = _artifact(source_compose, 8 * COMPOSE_LIMIT)
        prior = strict_json(current)
        model = _compose_value(strict_json(compose))
        old_op = self.store.get(UUID(prior.get("authorized_operation", prior["operation"])))
        if (
            not old_op or old_op.stage is not OperationStage.SUCCEEDED
            or old_op.request.release.manifest_digest != metadata["source_digest"]
            or old_op.request.release.release_id != prior["release_id"]
            or str(old_op.instance_id) != metadata["instance_id"]
            or prior["instance"] != metadata["instance_id"]
            or prior["manifest_digest"] != metadata["source_digest"]
            or prior["revision"] != metadata["source_revision"]
            or prior["compose_digest"] != digest_of(compose)
            or prior["config_digest"] != digest_of(_artifact(data / ".env"))
            or {role: image for role, image in prior["images"].items() if role != "migrate"}
            != metadata["source_images"]
            or any(model["services"][role]["image"] != image for role, image in prior["images"].items())
            or model["name"] != self.config["project"]
        ):
            raise ValueError("The previous verified application is unavailable")
        return marker, prior, model

    @staticmethod
    def _receipt(host, pg: str, operation, prior: dict, stage: OperationStage) -> str:
        previous = host.services["gateway"]["environment"].get(CONTEXT_ENV) or None
        revision = prior["revision"]
        new_database = host.database_identity(pg)
        old_context = {
            "operation": prior["operation"],
            "instance": str(operation.instance_id),
            "manifest": prior["manifest_digest"],
            "image": prior["images"]["gateway"].rsplit("@", 1)[-1],
            "target": revision,
            "database": prior["database"],
        }
        if (
            any(
                (host.services[role]["environment"].get(CONTEXT_ENV) or None) != previous
                for role in MANAGED_ROLES
            )
            or new_database == prior["database"]
            or host.revision(pg) != revision
        ):
            raise ValueError("The saved release context differs from the restored schema")
        if previous is None:
            if prior.get("legacy_adopted") is not True:
                raise ValueError("No verified baseline for the recovered schema")
            required_extensions = prior["required_extensions"]
            # Legacy adoption attested the actual running images and gate without
            # creating a fictitious successful migration record on the source.
            baseline = "true"
        else:
            context = strict_json(previous.encode())
            if any(context[key] != expected for key, expected in old_context.items()):
                raise ValueError("The old receipt does not describe the preserved application")
            required_extensions = context["required_extensions"]
            old_where = host.receipt_where(previous)
            baseline = f"EXISTS (SELECT 1 FROM {RECEIPTS} WHERE {old_where} AND phase = 'resumed')"

        encoded = canonical_json({
            **old_context, "operation": str(operation.id), "database": new_database,
            "source": revision, "required_extensions": required_extensions,
        }).decode()
        phase = host.phase(pg, encoded)
        if phase == "resumed" and stage is OperationStage.RESUMING:
            return encoded
        if host.sql(pg, frozen_sql(operation.id)) != "frozen":
            raise ValueError("The restored database is no longer frozen for this operation")
        if phase is None:
            # Create a receipt only for the checked schema and the still-frozen recovered DB.
            host.sql(pg, f"""
                BEGIN;
                SELECT pg_advisory_xact_lock({MIGRATION_LOCK_ID});
                CREATE SCHEMA IF NOT EXISTS dvt_release_control;
                CREATE TABLE IF NOT EXISTS {RECEIPTS} (
                    operation_id uuid PRIMARY KEY, context jsonb NOT NULL,
                    phase text NOT NULL CHECK (phase IN ('core', 'done', 'resumed'))
                );
                INSERT INTO {RECEIPTS} (operation_id, context, phase)
                SELECT '{operation.id}', {_literal(encoded)}::jsonb, 'done'
                WHERE {baseline}
                  AND EXISTS (SELECT 1 FROM task_admission_control
                              WHERE singleton = 1 AND operation_id = '{operation.id}' AND frozen)
                  AND (SELECT array_agg(version_num::text) FROM alembic_version)
                      = ARRAY[{_literal(revision)}]::text[]
                ON CONFLICT (operation_id) DO NOTHING;
                COMMIT;
            """)
        if host.phase(pg, encoded) != "done":
            raise ValueError("Could not establish a recovery receipt for the new database")
        return encoded

    @staticmethod
    def _verify_application(host, pg: str, proof: FunctionalProof) -> None:
        token = proof.access_cookie
        if len(token) > 8192 or not ACCESS_COOKIE.fullmatch(token):
            raise ApplyError(FailureReason.GATEWAY_UNAVAILABLE, "Invalid access-cookie encoding")
        project = str(proof.project) if proof.project is not None else ""
        if not project and host.sql(pg, "SELECT count(*) FROM projects") != "0":
            raise ApplyError(FailureReason.GATEWAY_UNAVAILABLE, "Select a preserved project")
        extensions = json.loads(host.sql(
            pg, "SELECT COALESCE(json_agg(name), '[]') FROM extensions WHERE is_installed",
        ))
        payload = canonical_json({"access_token": token, "extensions": extensions})
        if len(payload) > 32 * 1024:
            raise ApplyError(FailureReason.GATEWAY_UNAVAILABLE, "Recovery proof is too large")
        gateway = host.containers()["gateway"][0]["Id"]
        port = int(host.services["gateway"]["environment"].get("GATEWAY_PORT", 8000))
        subprocess.run(
            [
                "docker", "--host", f"unix://{SOCKET}", "exec", "--interactive", gateway,
                "python3", "-c", AUTH_PROBE, str(port), project,
            ],
            env=DOCKER_ENV, input=payload, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            check=True, timeout=35,
        )


def main() -> int:
    from ..candidate_executor import _probe

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["start", "finalize"])
    parser.add_argument("--dir", required=True, type=Path)
    parser.add_argument("--operation-id", required=True, type=UUID)
    parser.add_argument("--project-id", type=UUID)
    args = parser.parse_args()
    try:
        if os.geteuid():
            raise ValueError("Root is required for recovery")
        config = load_host(safe_path(args.dir))
        runtime = RestoreRuntime(OperationStore.for_host(args.dir), config, _probe)
        proof = None
        if args.action == "finalize":
            if not sys.stdin.isatty():
                raise ValueError("An administrative terminal is required to enter an access cookie")
            token = getpass.getpass("Fresh DVT administrator access_token cookie: ")
            proof = FunctionalProof(token, args.project_id)
        result = runtime.execute(args.operation_id, authorize=args.action == "start", proof=proof)
    except (OSError, ValueError, RuntimeError, TypeError, KeyError, subprocess.SubprocessError):
        result = False
    if not result:
        sys.stderr.write("Recovery paused. Review the operation journal before continuing.\n")
    return 0 if result else 1


if __name__ == "__main__":
    sys.exit(main())
