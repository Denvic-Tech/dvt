"""Admit browser-selected pins and prepare them in the detached executor."""

from __future__ import annotations

from pathlib import Path
from subprocess import SubprocessError

from ..domain.operation_state import (
    ArtifactKind,
    Checkpoint,
    CheckpointOutcome,
    FailureReason,
    OperationKind,
    OperationStage,
)
from ..domain.release_manifest import StagingError
from ..domain.services import generate_fernet_key, generate_password, resolve_auth_secrets
from ..host_bootstrap import CONTROL
from ..infrastructure.offline_host import local_trust
from ..infrastructure.staging_artifacts import read_artifact
from ..infrastructure.staging_commands import Deadline, RetryPolicy
from ..infrastructure.staging_docker import StagingDocker
from ..infrastructure.staging_downloads import ReleaseDownloader, https_origin
from ..infrastructure.staging_host import HostPaths, incompatible
from .offline_bundles import _configuration, _preparer_version
from .verified_staging import VerifiedStaging


def initial_settings() -> dict[str, str]:
    return {
        "DVT_FERNET_KEY": generate_fernet_key(),
        **resolve_auth_secrets({}),
        **{name: generate_password()
        for name in (
            "DVT_POSTGRES_PASSWORD", "DVT_VALKEY_PASSWORD",
            "DVT_AI_MCP_INTERNAL_SECRET", "DVT_GRPC_FORWARD_SERVICE_TOKEN",
        )},
    }


def prepare_online(config, store, operation):
    data = Path(config["data"])
    paths = HostPaths(
        Path(config["temporary"]), Path(config["backup"]),
        containerd_root=Path(config["containerd_root"]) if config["containerd_root"] else None,
        os_release=Path("/run/dvt-host-os"),
    )
    settings = config["release_catalog"]
    ca = data / CONTROL / "release-catalog-ca.pem"
    try:
        trust = local_trust(data, settings.get("trust"))
        docker = StagingDocker(
            data, data / CONTROL / "docker",
            registry_hosts=frozenset({
                "docker.io", "cr.distribution.denvic.tech", *settings.get("registry_hosts", ()),
            }),
        )
        downloader = ReleaseDownloader(
            frozenset({
                https_origin(settings["origin"]), "https://raw.distribution.denvic.tech",
                *settings.get("asset_origins", ()),
            }),
            ca_file=ca if read_artifact(ca, 128 * 1024) is not None else None,
        )
        source = None
        if operation.request.kind is OperationKind.UPDATE:
            source, _ = _configuration(config, store, Deadline(RetryPolicy(), paths.temporary), docker)
        manager = read_artifact(data / CONTROL / "current-manager", 4096)
        if manager is None:
            raise incompatible("The bootstrap manager digest is unavailable")
    except (OSError, ValueError, KeyError, RuntimeError, SubprocessError) as error:
        reason = error.reason if isinstance(error, StagingError) else FailureReason.INVALID_PACKAGE
        with store.claim(operation.id) as owner:
            current = store.get(operation.id)
            if current.stage is OperationStage.ADMITTED:
                current = owner.checkpoint(Checkpoint(OperationStage.PREPARING))
            if current.stage is OperationStage.PREPARING:
                owner.checkpoint(Checkpoint(current.stage, CheckpointOutcome.BLOCKED, reason))
        return False

    try:
        VerifiedStaging(
            store, trust, downloader, docker, paths, _preparer_version(),
            http_manager=config.get("manager_http") is True,
        ).prepare(
            operation.id, "", observed=source, applied=source.pin if source else None,
            bootstrap_image=manager.decode("ascii").strip(),
        )
    except StagingError:
        return False
    return True


def is_online(store, operation) -> bool:
    if operation.request.bundle_id is not None or operation.request.config_id is None:
        return False
    marker = store.artifact_path(ArtifactKind.CONFIG, operation.request.config_id) / "operator.json"
    return read_artifact(marker, 4096) is not None
