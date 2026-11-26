"""Import a supported legacy data directory into the managed 1.24.0 release."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import NAMESPACE_URL, UUID, uuid5

from ..domain.operation_state import (
    ArtifactKind,
    Checkpoint,
    CheckpointOutcome,
    FailureReason,
    InstanceIdentity,
    Observation,
    OperationKind,
    OperationRequest,
    OperationStage,
    OwnershipConflict,
    ReleasePin,
)
from ..domain.release_manifest import (
    REQUIRED_SERVICES,
    StagingError,
    canonical_json,
    digest_of,
    strict_json,
)
from ..host_bootstrap import (
    CONTROL,
    HOST_OS_RELEASE,
    PROJECT,
    _catalog_config,
    atomic_write,
    check_image,
    docker,
    image_store,
    init_container,
    launch,
    load_host,
    safe_path,
)
from ..infrastructure.application_host import DATABASE_ID, ComposeApplicationHost
from ..infrastructure.maintenance_archive import create_copy, preflight, verify_copy
from ..infrastructure.maintenance_host import PG_TARGET, ComposeMaintenanceHost
from ..infrastructure.offline_host import local_trust
from ..infrastructure.operation_files import sync_directory
from ..infrastructure.operation_store import FORMAT_VERSION, OperationStore
from ..infrastructure.operator_wiring import wire_gateway
from ..infrastructure.staging_artifacts import (
    CONFIG_KEY,
    artifact_directory,
    read_artifact,
    validate_config,
    write_artifact,
)
from ..infrastructure.staging_commands import Deadline, RetryPolicy
from ..infrastructure.staging_compose import (
    COMPOSE_LIMIT,
    _source_service,
    _target_service,
    check_model,
    effective_config,
    validate_template,
)
from ..infrastructure.staging_docker import StagingDocker, _compose_value, image_references
from ..logger import logger
from .application_apply import LIMIT, _artifact, _compose_literal, _dotenv, _validate_runtime
from .legacy_adopt import _containers
from .legacy_transition import _read, _same_service
from .release_catalog import version_tag

PLAN = "legacy-import.json"
ROLLBACK = "legacy-return-to-source.json"
ROLLBACK_STAGES = frozenset({
    OperationStage.PREPARING, OperationStage.PREPARED,
    OperationStage.MAINTENANCE, OperationStage.BACKUP,
})
# These published versions can still be installed with the pre-journal manager.
SOURCE_REVISIONS = {
    "1.22.0": "0061",
    "1.23.0": "0063",
    "1.24.0-rc1": "0065",
    "1.24.0-rc2": "0068",
    "1.24.0-rc3": "0069",
    "1.24.0-rc4": "0070",
    "1.24.0-rc5": "0063",
    **{f"1.24.0-rc{number}": "0070" for number in range(6, 13)},
}
CORE = {"postgres", "valkey", "installation_manager"}
APPLICATION = (REQUIRED_SERVICES - CORE - {"migrate"}) | {"dvt-ai-mcp"}
BRIDGE = "tech.denvic.legacy-bridge"
ERRORS = (OSError, ValueError, RuntimeError, KeyError, TypeError, subprocess.SubprocessError)
ONLY_LOCAL_CLIENT = """
SELECT count(*) FROM pg_stat_activity
WHERE backend_type = 'client backend' AND pid <> pg_backend_pid()
"""


def _backups(data: Path) -> tuple[Path, Path]:
    # The legacy updater backs up the dotenv before requesting and replacing Compose.
    def latest(name):
        pattern = re.compile(re.escape(name) + r"\.bak\.(\d{14})")
        items = [
            (match[1], path)
            for path in data.glob(name + ".bak.*")
            if (match := pattern.fullmatch(path.name))
        ]
        stamp, path = max(items, default=("", None))
        if path is None:
            raise ValueError("The legacy updater's source backups are missing")
        return datetime.strptime(stamp, "%Y%m%d%H%M%S"), path

    env_time, env = latest(".env")
    compose_time, compose = latest("docker-compose.yaml")
    if compose_time < env_time:
        raise ValueError("The legacy backups do not belong to the same attempt")
    return env, compose


def _old_model(data, project, env, compose):
    validate_template(_read(compose, COMPOSE_LIMIT))
    _read(env, LIMIT)
    args = (
        "compose",
        "--project-directory",
        str(data),
        "--project-name",
        project,
        "--file",
        str(compose),
        "--env-file",
        str(env),
        "--profile",
        "*",
        "config",
    )
    model = _compose_value(json.loads(docker(*args, "--format", "json").stdout))
    values = {
        name: value
        for line in docker(*args, "--environment").stdout.splitlines()
        if (pair := line.partition("="))[1]
        for name, _, value in (pair,)
        if CONFIG_KEY.fullmatch(name)
    }
    validate_config(values)
    if model["name"] != project or not model["services"].keys() >= CORE:
        raise ValueError("The backed up Compose belongs to another installation")
    return model, values


def _pgdata(data, source):
    path = Path(source)
    if path == data or not path.is_relative_to(data) or path.resolve(strict=True) != path:
        raise ValueError("PostgreSQL data is outside the canonical DVT directory")
    return path


def legacy_source_version(version: str, revision: str) -> str:
    # A historical latest tag has no recoverable version after the old updater
    # replaces its containers. Keep the alias and validate the observed schema.
    if version == "latest":
        if revision in SOURCE_REVISIONS.values():
            return version
    else:
        version = version_tag(version)
        if SOURCE_REVISIONS.get(version) == revision:
            return version
    raise ValueError("The legacy version and live database revision are unsupported")


def check_historical_migrator(roles: dict, services: dict) -> None:
    historical = roles.get("migrate", ())
    if historical and (
        "migrate" not in services or len(historical) != 1
        or historical[0]["State"]["Status"] not in {"created", "exited"}
    ):
        raise ValueError("The historical Compose migrator is unexpected or active")


def _source(data, project):
    env, compose = _backups(data)
    model, values = _old_model(data, project, env, compose)
    roles = _containers(project)
    check_historical_migrator(roles, model["services"])
    if (
        not roles.keys() >= CORE
        or roles.keys() - CORE - APPLICATION - {"migrate"}
        or not roles.get("orchestrator")
        or roles["orchestrator"][0]["Config"]["Labels"].get(BRIDGE) != "1"
    ):
        raise ValueError("The expected legacy bridge does not own this Compose project")
    for role, rows in roles.items():
        if len(rows) != 1 and role != "task-worker":
            raise ValueError("Unexpected replicas in the legacy project")
        for row in rows:
            state = row["State"]
            labels = row["Config"]["Labels"]
            if state["Paused"] or state["Restarting"]:
                raise ValueError("A legacy container is paused or restarting")
            if role not in CORE and labels.get(BRIDGE) != "1" and state["Running"]:
                raise ValueError("A legacy application service remains active")

    for role in CORE:
        (row,) = roles[role]
        # The old manager used /dvt-lib internally. It must still be the Compose
        # instance that initiated the update, with the expected bind and socket.
        image = docker("image", "inspect", model["services"][role]["image"])
        if json.loads(image.stdout)[0]["Id"] != row["Image"] or not row["State"]["Running"]:
            raise ValueError("The legacy infrastructure changed after the backups were made")
    (manager,) = roles["installation_manager"]
    (binding,) = _source_service(manager).bindings
    if binding.target != 8000 or binding.protocol != "tcp":
        raise ValueError("Unsupported legacy manager binding")
    instance = UUID(_read(data / "installation" / "instance_id", 128).decode().strip())
    identity = InstanceIdentity(
        instance,
        str(data),
        project,
        binding.address,
        binding.port,
        values["DVT_PUBLIC_URL"].split(";", 1)[0].strip(),
    )
    for role in CORE:
        observed = _source_service(roles[role][0])
        desired = _target_service(role, model["services"][role], model, identity)
        if not _same_service(observed, desired):
            raise ValueError("The observed legacy infrastructure differs from its backup")
    (pg,) = roles["postgres"]
    observed = _source_service(pg)
    (mount,) = observed.mounts
    if (
        mount.kind != "bind"
        or mount.target != PG_TARGET
        or mount.read_only
        or observed.bindings
        or not observed.networks
        or ComposeMaintenanceHost.sql(pg["Id"], "SHOW data_directory") != PG_TARGET
    ):
        raise ValueError("The import requires a private local PostgreSQL bind")
    pgdata = _pgdata(data, mount.source)
    revision = ComposeMaintenanceHost.sql(pg["Id"], "SELECT version_num FROM alembic_version")
    version = legacy_source_version(values.get("DVT_VERSION", ""), revision)
    database = ComposeMaintenanceHost.sql(pg["Id"], DATABASE_ID)
    if not re.fullmatch(r"[0-9]+:[0-9]+", database):
        raise ValueError("Could not establish the identity of the legacy database")

    # Retain the observed external network, application port, and all saved secrets.
    (network,) = observed.networks
    values["DVT_NETWORK_NAME"] = network
    values["DVT_NETWORK_EXTERNAL"] = "true"
    fallback = _pin_fallback(model, values)
    return (
        identity,
        roles,
        values,
        fallback,
        {
            "source_version": version,
            "source_revision": revision,
            "database": database,
            "pgdata": str(pgdata),
            "source_env": env.name,
            "source_compose": compose.name,
            "source_env_digest": digest_of(_read(env, LIMIT)),
            "source_compose_digest": digest_of(_read(compose, COMPOSE_LIMIT)),
        },
    )


def _pin_fallback(model, values):
    # The old updater already replaced the application containers. Only create
    # an automatic rollback plan when every enabled old image still has a local digest.
    profiles = set(values.get("COMPOSE_PROFILES", "").split(","))
    services = {
        name: dict(service)
        for name, service in model["services"].items()
        if not service.get("profiles") or profiles.intersection(service["profiles"])
    }
    for service in services.values():
        reference = service["image"]
        result = docker("image", "inspect", reference, check=False)
        if result.returncode:
            return None
        (image,) = json.loads(result.stdout)
        repository = re.sub(r"(?::[^/:]+|@sha256:[0-9a-f]{64})$", "", reference)
        references = sorted(
            ref
            for ref in image_references(image)
            if ref.partition("@")[0].removeprefix("docker.io/library/").removeprefix("docker.io/")
            == repository.removeprefix("docker.io/library/").removeprefix("docker.io/")
        )
        if not references:
            return None
        service["image"] = references[0]
    return canonical_json(_compose_literal({**model, "services": services}))


def _operation_id(job_id, instance):
    try:
        operation_id = UUID(job_id)
        if operation_id.int:
            return operation_id
    except ValueError:
        pass
    return uuid5(NAMESPACE_URL, f"dvt:{instance}:legacy-update:{job_id}")


def _host_config(args, identity):
    info = json.loads(docker("info", "--format", "{{json .}}").stdout)
    data = Path(identity.data_dir)
    root = safe_path(info["DockerRootDir"])
    containerd = safe_path(args.containerd_root) if args.containerd_root else None
    if image_store(info) and containerd is None:
        containerd = safe_path("/var/lib/containerd")
    if image_store(info) != bool(containerd) or any(
        path.is_relative_to(data) or data.is_relative_to(path)
        for path in (root, containerd)
        if path
    ):
        raise ValueError("The DVT data path overlaps Docker storage")
    check_image(args.executor)
    return {
        "version": 1,
        "instance": str(identity.instance_id),
        "data": identity.data_dir,
        "project": identity.compose_project,
        "address": identity.manager_address,
        "port": identity.manager_port,
        "public_url": identity.public_url,
        "manager": args.executor,
        "candidate": args.executor,
        "executor": args.executor,
        "manager_http": True,
        "docker_root": str(root),
        "containerd_root": str(containerd) if containerd else None,
        "backup": str(data / "backup"),
        "temporary": str(data / "tmp"),
        "release_catalog": _catalog_config(args.catalog_config, HOST_OS_RELEASE),
    }


def _initialize(data, config, catalog_ca):
    control = data / CONTROL
    if not control.exists():
        with TemporaryDirectory(prefix=".bootstrap-partial-", dir=data) as staging:
            directory = Path(staging)
            atomic_write(directory / "host.json", canonical_json(config))
            atomic_write(directory / "current-manager", config["manager"].encode())
            atomic_write(
                directory / "host_bootstrap.py",
                Path(__file__).parents[1].joinpath("host_bootstrap.py").read_bytes(),
            )
            if catalog_ca:
                atomic_write(directory / "release-catalog-ca.pem", _read(catalog_ca, 128 * 1024))
            directory.rename(control)
            sync_directory(data)
    if load_host(data) != config or (control / "current-release.json").exists():
        raise ValueError("A managed installation already owns this directory")
    for key in ("backup", "temporary"):
        safe_path(config[key]).mkdir(mode=0o700, parents=True, exist_ok=True)
    if init_container(config, "candidate-init"):
        raise ValueError("Unexpected response from the protected bootstrap")


def _prepare(args, data):
    from .legacy_baseline import load_baseline

    identity, roles, values, fallback, plan = _source(data, args.project)
    config = _host_config(args, identity)
    pin, _, _ = load_baseline(local_trust(data, config["release_catalog"].get("trust")))
    _initialize(data, config, args.catalog_ca)
    store = OperationStore.for_host(data)
    if store.identity() != identity:
        raise ValueError("The managed journal belongs to a different instance")
    operation = store.admit(
        OperationRequest(OperationKind.UPDATE, pin),
        idempotency_key="legacy-import:" + str(args.legacy_job_id),
        operation_id=_operation_id(args.legacy_job_id, identity.instance_id),
    )
    with store.claim(operation.id) as owner:
        directory = artifact_directory(store, ArtifactKind.STAGING, operation.id)
        write_artifact(directory / "legacy-values.json", canonical_json(values))
        if fallback is not None:
            write_artifact(directory / "legacy-return.compose.yaml", fallback)
        write_artifact(
            directory / PLAN,
            canonical_json(
                {
                    **plan,
                    "legacy_job_id": args.legacy_job_id,
                    "fallback_digest": digest_of(fallback) if fallback else None,
                    "target_version": args.version,
                    "target_manifest_digest": args.manifest_digest,
                    "source_images": {
                        role: sorted({row["Image"] for row in rows}) for role, rows in roles.items()
                    },
                    "postgres_id": roles["postgres"][0]["Id"],
                    "valkey_id": roles["valkey"][0]["Id"],
                    "settings_digest": digest_of(canonical_json(values)),
                }
            ),
        )
        if operation.stage is OperationStage.ADMITTED:
            owner.checkpoint(Checkpoint(OperationStage.PREPARING))
    return config, str(operation.id)


def _target(config, store, operation, directory, saved):
    from .legacy_baseline import load_baseline

    trust = local_trust(Path(config["data"]), config["release_catalog"].get("trust"))
    pin, release, content = load_baseline(trust)
    if pin != operation.request.release:
        raise ValueError("The protected baseline release pin changed")
    raw_values = _artifact(directory / "legacy-values.json")
    if digest_of(raw_values) != saved["settings_digest"]:
        raise ValueError("The protected source settings changed")
    values = strict_json(raw_values)
    env, profiles = effective_config(values, store.identity(), operation.request, release.version)
    platform = config["release_catalog"]["platform"]
    distribution = release.platforms[platform]
    compose = directory / "compose.yaml"
    atomic_write(compose, content)
    validate_template(content)
    deadline = Deadline(RetryPolicy(), Path(config["temporary"]))
    adapter = StagingDocker(
        directory,
        Path("/root/.docker"),
        registry_hosts=frozenset(
            {
                "docker.io",
                "cr.distribution.denvic.tech",
                *config["release_catalog"].get("registry_hosts", ()),
            }
        ),
    )
    active = adapter.config(compose, config["project"], profiles, env, deadline)
    full = adapter.config(compose, config["project"], ("*",), env, deadline)
    check_model(active, store.identity(), distribution, env, active=True)
    check_model(full, store.identity(), distribution, env, active=False)
    _validate_runtime(active)
    for role, model in active["services"].items():
        _target_service(role, model, active, store.identity())
    pg_config = active["services"]["postgres"]
    if pg_config["volumes"][0]["source"] != saved["pgdata"]:
        raise ValueError("The baseline would move the existing PostgreSQL data")
    full["services"]["installation_manager"].update(
        image=config["manager"],
        command=["candidate-web", config["data"]],
    )
    wire_gateway(full["services"], config)
    services = {role: full["services"][role]["image"] for role in active["services"]}
    if operation.stage is OperationStage.PREPARING:
        for reference in set(services.values()) - {config["manager"]}:
            if not adapter.local_image(reference, platform, deadline):
                adapter.pull(reference, platform, deadline)
    host = ComposeApplicationHost(
        config,
        directory,
        full,
        {
            "platform": platform,
            "profiles": profiles,
            "services": services,
            "observed_images": {},
            "retire": [],
        },
        deadline,
    )
    # The protected bridge manager may itself be a signed multi-architecture index.
    host.config = {**config, "local_manager_image": config["manager"]}
    host.bind_images()
    compose_bytes = canonical_json(_compose_literal(full))
    atomic_write(host.path, compose_bytes)
    return host, release, compose_bytes, env


def _rows(config, host, saved):
    rows = _containers(config["project"])
    if rows.keys() - (host.services.keys() | saved["source_images"].keys()):
        raise ValueError("Unexpected role in the legacy project")
    for role, containers in rows.items():
        allowed = set(saved["source_images"].get(role, ()))
        if role in host.services:
            allowed.add(host.image_ids[host.plan["services"][role]])
        if any(row["Image"] not in allowed for row in containers):
            raise ValueError("A container does not belong to the staged project")
    return rows


def _stop_application(rows):
    ids = [
        row["Id"] for role, containers in rows.items() if role in APPLICATION for row in containers
    ]
    if ids:
        docker("container", "update", "--restart=no", *ids)
        docker("container", "stop", "--timeout", "30", *ids, timeout=150)


def _seal(config, host, saved):
    rows = _rows(config, host, saved)
    (pg,) = rows["postgres"]
    if (
        pg["Id"] != saved["postgres_id"]
        or any(
            row["State"]["Running"]
            for role, containers in rows.items()
            if role in APPLICATION | {"migrate"}
            for row in containers
        )
        or ComposeMaintenanceHost.sql(pg["Id"], ONLY_LOCAL_CLIENT) != "0"
        or ComposeMaintenanceHost.sql(pg["Id"], "SELECT version_num FROM alembic_version")
        != saved["source_revision"]
        or host.database_identity(pg["Id"]) != saved["database"]
    ):
        raise ValueError("The legacy database has not been isolated from writers")
    return pg["Id"]


def _run_roles(host, *services):
    docker(
        "compose",
        "--project-name",
        host.config["project"],
        "--project-directory",
        host.config["data"],
        "--env-file",
        "/dev/null",
        "--file",
        str(host.path),
        "up",
        "--detach",
        "--no-deps",
        "--pull",
        "never",
        "--no-build",
        *services,
    )


def _backup_metadata(config, operation_id, directory, saved):
    return {
        "format_version": 1,
        "operation_id": str(operation_id),
        "instance_id": config["instance"],
        "layout": strict_json(_artifact(directory / "legacy-backup-layout.json")),
        "legacy_source": saved,
    }


def return_to_legacy(config, store, operation_id, *, legacy_job: dict | None = None):
    """Reconcile the verified source only while no migration has been authorized."""
    directory = artifact_directory(store, ArtifactKind.STAGING, operation_id)
    with store.claim(operation_id) as owner:
        operation = store.get(operation_id)
        if operation.stage not in ROLLBACK_STAGES:
            raise ValueError("Legacy rollback is only available before migration")
        data = Path(config["data"])
        saved = strict_json(_artifact(directory / PLAN))
        if (
            operation.request.kind is not OperationKind.UPDATE
            or operation_id != _operation_id(saved["legacy_job_id"], operation.instance_id)
            or str(operation.instance_id) != config["instance"]
            or os.path.lexists(data / CONTROL / "current-release.json")
        ):
            raise ValueError("The rollback does not belong to the original legacy update")

        fallback_path = directory / "legacy-return.compose.yaml"
        fallback = _artifact(fallback_path, 8 * COMPOSE_LIMIT)
        env = _read(data / saved["source_env"], LIMIT)
        compose = _read(data / saved["source_compose"], COMPOSE_LIMIT)
        if (
            digest_of(fallback) != saved["fallback_digest"]
            or digest_of(env) != saved["source_env_digest"]
            or digest_of(compose) != saved["source_compose_digest"]
        ):
            raise ValueError("The protected legacy rollback files changed")
        roles = _containers(config["project"])
        (pg,) = roles["postgres"]
        (valkey,) = roles["valkey"]
        sql = ComposeMaintenanceHost.sql
        model = strict_json(fallback)
        images = {
            role: check_image(service["image"]) for role, service in model["services"].items()
        }
        pending = read_artifact(directory / ROLLBACK, LIMIT)
        if (
            pg["Image"] != images["postgres"]
            or (pending is None and pg["Id"] != saved["postgres_id"])
            or valkey["Image"] != images["valkey"]
            or valkey["Id"] != saved.get("valkey_id", valkey["Id"])
            or not valkey["State"]["Running"]
            or sql(pg["Id"], "SELECT version_num FROM alembic_version") != saved["source_revision"]
            or sql(pg["Id"], DATABASE_ID) != saved["database"]
        ):
            raise ValueError("The legacy database cannot be restarted on its old application")
        values = strict_json(_artifact(directory / "legacy-values.json"))
        workers = int(values.get("DVT_TASK_WORKERS_COUNT", "1"))
        if workers < 1:
            raise ValueError("The backed up worker count is invalid")

        resume = strict_json(pending) if pending is not None else {"operation": str(operation_id)}
        if resume["operation"] != str(operation_id):
            raise ValueError("The saved rollback belongs to another operation")
        if pending is None and legacy_job is not None:
            from ..legacy_entry_recovery import rollback_job

            if (
                legacy_job["job_id"] != saved["legacy_job_id"] or legacy_job["kind"] != "update"
                or legacy_job["project"] != config["project"]
                or legacy_job["target_version"] != saved["target_version"]
                or legacy_job["manifest_digest"] != saved["target_manifest_digest"]
                or legacy_job["requested_version"] not in {"latest", saved["target_version"]}
            ):
                raise ValueError("The previous browser job differs from the admitted request")
            resume["browser_job"] = rollback_job(legacy_job)

        write_artifact(directory / ROLLBACK, canonical_json(resume))
        if browser_job := resume.get("browser_job"):
            from ..legacy_entry_recovery import configure_rollback_manager

            configure_rollback_manager(model, browser_job)
            fallback_path = directory / "legacy-return-reported.compose.yaml"
            write_artifact(fallback_path, canonical_json(model))

        atomic_write(data / ".env", env)
        atomic_write(data / "docker-compose.yaml", compose)
        docker(
            "compose",
            "--project-name",
            config["project"],
            "--project-directory",
            str(data),
            "--env-file",
            "/dev/null",
            "--file",
            str(fallback_path),
            "--profile",
            "*",
            "up",
            "--detach",
            "--wait",
            "--wait-timeout",
            "180",
            "--no-deps",
            "--no-build",
            "--pull",
            "never",
            "--remove-orphans",
            "--scale",
            f"task-worker={workers}",
            *sorted(images.keys() - {"postgres", "valkey", "migrate"}),
            timeout=200,
        )
        actual = _containers(config["project"])
        check_historical_migrator(actual, model["services"])
        if (
            actual.keys() - {"migrate"} != images.keys() - {"migrate"}
            or actual["postgres"][0]["Id"] != pg["Id"]
            or actual["valkey"][0]["Id"] != valkey["Id"]
            or len(actual["task-worker"]) != workers
            or any(
                row["Image"] != images[role] or not row["State"]["Running"]
                for role, rows in actual.items()
                if role != "migrate"
                for row in rows
            )
        ):
            raise ValueError("Compose did not restart the backed up legacy application")
        owner.checkpoint(Checkpoint(OperationStage.CANCELLED, CheckpointOutcome.VERIFIED))


def _migrate(host, saved, target_revision):
    (pg,) = _rows(host.config, host, saved)["postgres"]
    revision = host.revision(pg["Id"])
    if host.database_identity(pg["Id"]) != saved["database"] or revision not in {
        saved["source_revision"],
        target_revision,
    }:
        raise ValueError("The legacy database changed before migration")
    if not host.is_target("postgres", pg) or "Health" not in pg["State"]:
        pgdata = _pgdata(Path(host.config["data"]), saved["pgdata"])
        pg_major = (pgdata / "PG_VERSION").read_text(encoding="ascii").strip()
        (image,) = json.loads(docker("image", "inspect", host.plan["services"]["postgres"]).stdout)
        if f"PG_MAJOR={pg_major}" not in image["Config"]["Env"]:
            raise ValueError("The baseline would change the PostgreSQL major version")
        _run_roles(host, "postgres")
    stop = time.monotonic() + 100
    while time.monotonic() < stop:
        rows = _rows(host.config, host, saved)
        pg = rows["postgres"][0]
        if pg["State"].get("Health", {}).get("Status") == "healthy":
            pg_id = host.postgres(rows)
            break
        time.sleep(2)
    else:
        raise ValueError("The baseline PostgreSQL did not become healthy")
    if host.database_identity(pg_id) != saved["database"]:
        raise ValueError("The baseline PostgreSQL uses a different database")
    (migrate,) = rows.get("migrate", [None])
    finished_target = (
        migrate is not None
        and host.is_target("migrate", migrate)
        and migrate["State"]["Status"] == "exited"
        and migrate["State"]["ExitCode"] == 0
    )
    if not finished_target and (migrate is None or not migrate["State"]["Running"]):
        if host.sql(pg_id, ONLY_LOCAL_CLIENT) != "0":
            raise ValueError("A client is still connected to the legacy database")
        _run_roles(host, "migrate")
    stop = time.monotonic() + 900
    while time.monotonic() < stop:
        (migrate,) = _rows(host.config, host, saved).get("migrate", [None])
        if migrate is not None and migrate["State"]["Status"] == "exited":
            if (
                migrate["State"]["ExitCode"] == 0
                and host.is_target("migrate", migrate)
                and host.revision(pg_id) == target_revision
                and host.sql(
                    pg_id,
                    "SELECT 'open' FROM task_admission_control "
                    "WHERE singleton = 1 AND operation_id IS NULL AND NOT frozen",
                )
                == "open"
            ):
                return
            raise ValueError("The signed baseline migrator did not complete")
        time.sleep(2)
    raise ValueError("The signed baseline migration is still in progress")


def execute(config, store, operation_id, probe):
    from .update_route import attach_legacy_route, continue_legacy_update

    directory = artifact_directory(store, ArtifactKind.STAGING, operation_id)
    saved = strict_json(_artifact(directory / PLAN))
    data = Path(config["data"])
    operation = store.get(operation_id)
    if not operation.stage.terminal and read_artifact(directory / ROLLBACK, LIMIT) is not None:
        return_to_legacy(config, store, operation_id)
        return
    if operation.stage is OperationStage.SUCCEEDED:
        continue_legacy_update(config, store, operation_id)
        return
    if operation.stage.terminal:
        return
    with contextlib.suppress(OwnershipConflict), store.claim(operation_id) as owner:
        operation = store.get(operation_id)
        stage = operation.stage
        reason = FailureReason.INCOMPATIBLE_RELEASE
        try:
            if (
                operation.request.kind is not OperationKind.UPDATE
                or operation.id != _operation_id(saved["legacy_job_id"], operation.instance_id)
                or str(operation.instance_id) != config["instance"]
            ):
                raise ValueError("The import plan does not belong to this installation")
            legacy_source_version(saved["source_version"], saved["source_revision"])
            if stage is OperationStage.ADMITTED:
                stage = owner.checkpoint(Checkpoint(OperationStage.PREPARING)).stage
            host, release, compose, env = _target(config, store, operation, directory, saved)
            target = release.database_schema.target_revision
            if stage is OperationStage.PREPARING:
                for key, limit in (("env", LIMIT), ("compose", COMPOSE_LIMIT)):
                    if (
                        digest_of(_read(data / saved["source_" + key], limit))
                        != saved["source_" + key + "_digest"]
                    ):
                        raise ValueError("The legacy source backups changed")
                if init_container(config, "candidate-inspect") != str(FORMAT_VERSION):
                    raise ValueError("The protected manager cannot read the existing journal")
                pg = _rows(config, host, saved)["postgres"][0]
                planned = _target_service(
                    "postgres", host.services["postgres"], host.model, store.identity()
                )
                valkey = _rows(config, host, saved)["valkey"][0]
                planned_valkey = _target_service(
                    "valkey",
                    host.services["valkey"],
                    host.model,
                    store.identity(),
                )
                if not _same_service(_source_service(pg), planned) or not _same_service(
                    _source_service(valkey), planned_valkey
                ):
                    raise ValueError("The baseline would change database or Valkey storage")
                attach_legacy_route(
                    config, store, operation, saved["target_version"], saved["target_manifest_digest"], env,
                )
                stage = owner.checkpoint(
                    Checkpoint(
                        OperationStage.PREPARED,
                        CheckpointOutcome.VERIFIED,
                        observation=Observation(
                            source_revision=saved["source_revision"],
                            target_revision=target,
                            target_digest=operation.request.release.manifest_digest,
                            staging_id=operation.id,
                        ),
                    )
                ).stage
            if stage is OperationStage.PREPARED:
                stage = owner.checkpoint(Checkpoint(OperationStage.MAINTENANCE)).stage
            if stage is OperationStage.MAINTENANCE:
                reason = FailureReason.BACKUP
                _stop_application(_rows(config, host, saved))
                stage = owner.checkpoint(Checkpoint(OperationStage.BACKUP)).stage
            if stage is OperationStage.BACKUP:
                reason = FailureReason.MANAGER_UNAVAILABLE
                _run_roles(host, "installation_manager")
                probe(config, store, operation_id, owner.record.claim_id)
                reason = FailureReason.BACKUP
                pg = _seal(config, host, saved)
                backup = safe_path(config["backup"])
                layout_path = directory / "legacy-backup-layout.json"
                if read_artifact(layout_path, LIMIT) is None:
                    layout = preflight(
                        data, backup, Path(config["temporary"]), Path(saved["pgdata"])
                    )
                    atomic_write(layout_path, canonical_json(layout))
                metadata = _backup_metadata(config, operation_id, directory, saved)
                backup_host = ComposeMaintenanceHost(config, operation_id, {})
                create_copy(
                    backup,
                    operation_id,
                    metadata,
                    backup_host,
                    pg,
                    confirm_source_sealed=lambda: _seal(config, host, saved),
                )
                owner.checkpoint(
                    Checkpoint(
                        OperationStage.BACKUP,
                        CheckpointOutcome.VERIFIED,
                        observation=Observation(backup_id=operation_id),
                    )
                )
                stage = owner.checkpoint(Checkpoint(OperationStage.MIGRATING)).stage
            if stage is OperationStage.MIGRATING:
                reason = FailureReason.BACKUP
                (pg,) = _rows(config, host, saved)["postgres"]
                verify_copy(
                    safe_path(config["backup"]) / str(operation_id),
                    _backup_metadata(config, operation_id, directory, saved),
                    ComposeMaintenanceHost(config, operation_id, {}),
                    pg["Id"],
                )
                reason = FailureReason.MIGRATION
                _migrate(host, saved, target)
                stage = owner.checkpoint(
                    Checkpoint(
                        OperationStage.APPLYING,
                        CheckpointOutcome.VERIFIED,
                        observation=Observation(observed_revision=target),
                    )
                ).stage

            reason = FailureReason.COMPOSE
            if stage is OperationStage.APPLYING:
                # An inactive profile is still present in the full Compose file.
                # Retire its stopped placeholder explicitly so readiness sees only active roles.
                for role, rows in _rows(config, host, saved).items():
                    if role not in host.services:
                        if any(row["State"]["Running"] for row in rows):
                            raise ValueError("A service outside the selected profile is active")
                        docker("container", "rm", *(row["Id"] for row in rows))
                # The target migrator has already succeeded. Start the other roles
                # without rerunning it or waiting on Compose's dependency health gates.
                _run_roles(host, *sorted(host.services.keys() - {"migrate"}))
                stage = owner.checkpoint(Checkpoint(OperationStage.VERIFYING)).stage
            if stage in {OperationStage.VERIFYING, OperationStage.RESUMING}:
                reason = FailureReason.PROFILE_UNHEALTHY
                pg = host.wait_for_database()
                if (
                    host.database_identity(pg) != saved["database"]
                    or host.revision(pg) != target
                    or not host.wait_for_application(
                        pg,
                        None,
                        None,
                        store.identity().public_url,
                        int(env["DVT_TASK_WORKERS_COUNT"]),
                    )
                ):
                    raise ValueError("The baseline application did not become ready")
                probe(config, store, operation_id, owner.record.claim_id)
                env_bytes = _dotenv(env)
                atomic_write(data / ".env", env_bytes)
                atomic_write(data / "docker-compose.yaml", compose)
                atomic_write(
                    data / CONTROL / "current-release.json",
                    canonical_json(
                        {
                            "format_version": 1,
                            "operation": str(operation_id),
                            "instance": config["instance"],
                            "version": release.version,
                            "release_id": release.release_id,
                            "manifest_digest": operation.request.release.manifest_digest,
                            "revision": target,
                            "database": saved["database"],
                            "compose_digest": digest_of(compose),
                            "config_digest": digest_of(env_bytes),
                            "profiles": list(host.plan["profiles"]),
                            "images": host.plan["services"],
                            "legacy_adopted": True,
                        }
                    ),
                )
                if stage is OperationStage.VERIFYING:
                    stage = owner.checkpoint(
                        Checkpoint(
                            OperationStage.RESUMING,
                            CheckpointOutcome.VERIFIED,
                        )
                    ).stage
                owner.checkpoint(Checkpoint(OperationStage.SUCCEEDED, CheckpointOutcome.VERIFIED))
        except ERRORS as error:
            if isinstance(error, StagingError):
                reason = error.reason
            owner.checkpoint(Checkpoint(stage, CheckpointOutcome.RETRYABLE_ERROR, reason))
            logger.warning(
                "Импорт прежней установки приостановлен на этапе %s: %s", stage.value, reason.value
            )
            return
    if store.get(operation_id).stage is OperationStage.SUCCEEDED:
        continue_legacy_update(config, store, operation_id)


def main():
    import fcntl

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", required=True, type=Path)
    parser.add_argument("--project", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--manifest-digest", required=True)
    parser.add_argument("--legacy-job-id", required=True)
    parser.add_argument("--executor", required=True)
    parser.add_argument("--catalog-config", type=Path, required=True)
    parser.add_argument("--catalog-ca", type=Path)
    parser.add_argument("--containerd-root")
    args = parser.parse_args()
    os.umask(0o077)
    try:
        if os.geteuid() or not PROJECT.fullmatch(args.project):
            raise ValueError("The legacy bridge requires root and an explicit Compose project")
        args.version = version_tag(args.version)
        ReleasePin(args.version, args.manifest_digest)
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", args.legacy_job_id):
            raise ValueError("Invalid legacy operation ID")
        data = safe_path(args.dir)
        instance = UUID(_read(data / "installation" / "instance_id", 128).decode().strip())
        operation_id = _operation_id(args.legacy_job_id, instance)
        with safe_path(data / ".legacy-import.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            plan = (
                OperationStore.for_host(data).artifact_path(
                    ArtifactKind.STAGING,
                    operation_id,
                )
                / PLAN
                if (data / CONTROL / "host.json").is_file()
                else None
            )
            if plan is not None and plan.is_file():
                config, operation = load_host(data), str(operation_id)
                saved = strict_json(_artifact(plan))
                if (
                    config["project"] != args.project
                    or config["executor"] != args.executor
                    or saved["target_version"] != args.version
                    or saved["target_manifest_digest"] != args.manifest_digest
                ):
                    raise ValueError("The resumed import does not match its saved request")
            else:
                config, operation = _prepare(args, data)
            launch(config, operation)
    except ERRORS as error:
        message = error.reason.value if isinstance(error, StagingError) else type(error).__name__
        sys.stderr.write(f"Legacy import could not start: {message}.\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
