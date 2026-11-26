"""Admit a clean legacy-form submission into the normal first-install operation."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from uuid import UUID

from packaging.version import Version

from .application.legacy_adopt import _containers
from .application.legacy_import import _host_config, _initialize
from .application.legacy_transition import _read
from .catalog_api import configured_catalog
from .domain.operation_state import (
    ArtifactKind,
    InstanceIdentity,
    OperationKind,
    OperationRequest,
    OperationStage,
)
from .domain.release_manifest import canonical_json
from .domain.services import parse_env_file
from .host_bootstrap import CONTROL, STATE, apply_manager, check_image, docker, launch, safe_path
from .infrastructure.operation_store import OperationStore
from .infrastructure.staging_artifacts import CONFIG_KEY, save_config, write_artifact
from .infrastructure.staging_compose import _source_service
from .legacy_entry import LABEL, LEGACY_COMPOSE, _is_legacy_manager
from .legacy_entry_supervisor import initial_install_id

PLACEHOLDERS = {
    "orchestrator", "task-worker", "project-scheduler", "gateway", "dvt-ai-mcp", "ui", "proxy",
}


def _clean_scope(roles: dict, project: str, data: Path, image: str) -> tuple[dict, list[str]]:
    [manager] = roles["installation_manager"]
    if roles.keys() - PLACEHOLDERS - {"installation_manager"}:
        raise ValueError("Existing application data services prevent a legacy initial installation")
    removals = []
    for role in roles.keys() & PLACEHOLDERS:
        for row in roles[role]:
            config = row["Config"]
            labels = config["Labels"]
            if (
                labels.get(LABEL) != "1"
                or labels["com.docker.compose.project.config_files"] != LEGACY_COMPOSE
                or config["Image"] != image or (row["Mounts"] and role != "orchestrator")
            ):
                raise ValueError("The project includes an application service outside the bridge")
            removals.append(row["Id"])
    if manager["Config"]["Image"] != image and not _is_legacy_manager(manager, project, data):
        raise ValueError("The project includes a manager outside the bridge")
    return manager, removals


def _fresh_settings(data: Path, project: str, manager: dict, marker: dict):
    for name in ("pgdata", "valkeydata"):
        storage = safe_path(data / "data" / name)
        if storage.exists() and any(storage.iterdir()):
            raise ValueError("The old installer directory already contains application data")
    values = parse_env_file(_read(data / ".env", 256 * 1024).decode())
    if (
        values.get("COMPOSE_PROJECT_NAME") != project
        or values.get("DVT_LIB_DIR") != str(data)
        or values.get("DVT_VERSION") != marker["requested_version"]
    ):
        raise ValueError("The selected legacy installation changed")
    values = {name: value for name, value in values.items() if CONFIG_KEY.fullmatch(name)}
    [binding] = _source_service(manager).bindings
    if binding.target != 8000 or binding.protocol != "tcp":
        raise ValueError("Unsupported legacy manager binding")
    identity = InstanceIdentity(
        UUID(_read(data / "installation" / "instance_id", 128).decode().strip()),
        str(data), project, binding.address, binding.port, values["DVT_PUBLIC_URL"].split(";", 1)[0],
    )
    # The normal bootstrap Compose creates this project network for the manager.
    values["DVT_NETWORK_NAME"] = f"{project}_default"
    values["DVT_NETWORK_EXTERNAL"] = "true"
    return identity, values


def first_install(data: Path, image: str, marker: dict, package: Path) -> None:
    project = marker["project"]
    key = f'legacy-install:{marker["job_id"]}'
    identifier = initial_install_id(project, marker["job_id"])
    previous = None
    if (data / STATE / "journal.sqlite3").is_file():
        previous = OperationStore.for_host(data).get(identifier)
    if previous is not None and previous.stage is not OperationStage.ADMITTED:
        return
    roles = _containers(project)
    manager, removals = _clean_scope(roles, project, data, image)
    identity, values = _fresh_settings(data, project, manager, marker)
    config = _host_config(
        Namespace(containerd_root=None, executor=image, catalog_config=package / "catalog.json"),
        identity,
    )
    _initialize(data, config, None)
    store = OperationStore.for_host(data)
    if previous is None:
        catalog = configured_catalog(config)
        snapshot = catalog.refresh()
        row = next((
            release for release in snapshot.releases
            if release.version == marker["target_version"]
            and release.manifest_digest == marker["manifest_digest"]
        ), None)
        if marker["requested_version"] == "latest" and (row is None or not row.initial_install):
            paths = catalog.paths(snapshot, None)
            row = max(
                (path[-1] for path in paths.values() if Version(path[-1].version)
                 <= Version(marker["target_version"])),
                key=lambda release: Version(release.version), default=None,
            )
        if row is None:
            raise ValueError("The pinned release is unavailable for an initial installation")
        selected = catalog.select(row, None)
        config_id = save_config(store, values)
        write_artifact(
            store.artifact_path(ArtifactKind.CONFIG, config_id) / "operator.json",
            canonical_json({
                "kind": "install", "version": row.version, "manifest_digest": row.manifest_digest,
            }),
        )
        previous = store.admit(
            OperationRequest(OperationKind.INSTALL, selected.pin, config_id=config_id),
            idempotency_key=key, operation_id=identifier,
        )
    elif (
        store.identity() != identity
        or (
            marker["requested_version"] != "latest"
            and previous.request.release.manifest_digest != marker["manifest_digest"]
        )
    ):
        raise ValueError("The pending first installation differs from the pinned release")
    if removals:
        docker("container", "rm", "--force", *removals)
    if manager["Image"] != check_image(image):
        apply_manager(config, config["manager"], data / CONTROL / "bootstrap.compose.yaml")
    launch(config, str(previous.id))
