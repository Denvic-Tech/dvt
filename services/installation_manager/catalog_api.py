"""Protected catalog endpoints for the candidate installation manager."""

from __future__ import annotations

import json
import re
from pathlib import Path
from subprocess import SubprocessError
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException

from core.operator_contract import SelectRelease

from .application.legacy_adopt import _containers
from .application.release_catalog import (
    CatalogHost,
    ReleaseCatalog,
    SourceFacts,
    version_tag,
)
from .candidate_auth import CandidateAuth
from .domain.operation_state import FailureReason, ReleasePin
from .domain.release_manifest import StagingError, strict_json
from .host_bootstrap import CONTROL, docker
from .infrastructure.application_host import DATABASE_ID
from .infrastructure.maintenance_host import ComposeMaintenanceHost
from .infrastructure.operation_store import OperationStore
from .infrastructure.release_verification import TrustPolicy
from .infrastructure.staging_artifacts import read_artifact
from .infrastructure.staging_commands import Deadline, RetryPolicy
from .infrastructure.staging_docker import image_references
from .infrastructure.staging_downloads import ReleaseDownloader

# The selection endpoint is also used by existing protected clients.
Selection = SelectRelease


def initial_release(config: dict) -> SelectRelease | None:
    """Read the optional first-install pin from the root-owned launcher settings."""
    try:
        raw = read_artifact(Path(config["data"]) / CONTROL / "launch-host.conf", 16384)
        if raw is None:
            return None
        lines = raw.decode("ascii").splitlines()
        if len(lines) == 5:
            return None
        if len(lines) != 6:
            raise ValueError
        version, digest = lines[5].split(" ")
        return SelectRelease(version=version, manifest_digest=digest)
    except (StagingError, OSError, ValueError):
        raise HTTPException(409, "Invalid saved initial release selection") from None


def observe_source(config: dict, store: OperationStore) -> SourceFacts | None:
    """Establish the source from matching runtime image, database and committed release."""
    if store.active() is not None:
        raise ValueError("An operation owns the current source")
    data = Path(config["data"])
    contents = read_artifact(data / CONTROL / "current-release.json", 128 * 1024)
    roles = _containers(config["project"])
    if contents is None:
        # A legacy, partially installed or removed stack is not a fresh installation.
        if (
            roles.keys() - {"installation_manager"}
            or any((data / name).exists() or (data / name).is_symlink() for name in (
                "docker-compose.yaml", ".env", "data",
            ))
        ):
            raise ValueError("No supported source release has been established")
        return None

    current = strict_json(contents)
    if (
        type(current["format_version"]) is not int
        or current["format_version"] != 1
        or current["instance"] != config["instance"]
    ):
        raise ValueError("The current release belongs to a different instance")
    # Do not use DVT_VERSION from .env, Compose labels, or the container environment.
    (gateway,) = roles.get("gateway", ())
    (postgres,) = roles.get("postgres", ())
    if not gateway["State"]["Running"] or not postgres["State"]["Running"]:
        raise ValueError("The current source is not running")
    if roles.get("migrate") and any(row["State"]["Running"] for row in roles["migrate"]):
        raise ValueError("A migration is running")
    (image,) = json.loads(docker("image", "inspect", gateway["Image"], timeout=10).stdout)
    if current["images"]["gateway"] not in image_references(image):
        raise ValueError("The running Gateway image differs from the committed release")
    pg = postgres["Id"]
    revision = ComposeMaintenanceHost.sql(pg, "SELECT version_num FROM alembic_version")
    if (
        not re.fullmatch(r"[0-9a-f]{4,32}", revision)
        or revision != current["revision"]
        or ComposeMaintenanceHost.sql(pg, DATABASE_ID) != current["database"]
    ):
        raise ValueError("The observed database differs from the committed release")
    return SourceFacts(version_tag(current["version"]), revision)


def configured_catalog(config: dict) -> ReleaseCatalog:
    data = Path(config["data"])
    raw = read_artifact(data / CONTROL / "host.json", 128 * 1024)
    saved = strict_json(raw) if raw is not None else config
    if saved["instance"] != config["instance"] or saved["data"] != config["data"]:
        raise ValueError("The release catalog belongs to a different host")
    selected = saved["release_catalog"]
    origin = selected["origin"]
    override = read_artifact(data / CONTROL / "release-trust.json", 128 * 1024)
    trust_doc = strict_json(override) if override is not None else selected.get("trust")
    trust = None
    if override is not None or trust_doc is not None:
        if (
            not isinstance(trust_doc, dict) or set(trust_doc) != {"roots", "revoked_signers"}
            or not isinstance(trust_doc["roots"], dict) or not trust_doc["roots"]
            or any(not re.fullmatch(r"[0-9a-f]{64}", value) for value in trust_doc["roots"].values())
            or not isinstance(trust_doc["revoked_signers"], list)
            or any(
                not re.fullmatch(r"sha256:[0-9a-f]{64}", value)
                for value in trust_doc["revoked_signers"]
            )
        ):
            raise ValueError("The release trust policy is invalid")
        trust = TrustPolicy.from_document(trust_doc)

    ca = data / CONTROL / "release-catalog-ca.pem"
    catalog = ReleaseDownloader(
        frozenset({origin}), ca_file=ca if read_artifact(ca, 128 * 1024) is not None else None
    )

    def download(url: str, limit: int) -> bytes:
        return catalog.get(
            url, limit, cwd=data / CONTROL,
            deadline=Deadline(RetryPolicy(total_seconds=6, io_seconds=5, attempts=1)),
        )

    def verify(content: bytes, pin: ReleasePin):
        assert trust is not None
        return trust.verify(content, pin)

    return ReleaseCatalog(
        data=data, origin=origin,
        host=CatalogHost(selected["platform"], selected["distribution"], selected["distribution_version"]),
        download=download, verify=verify if trust else None,
    )


_OBSERVATION_ERRORS = (KeyError, TypeError, OSError, RuntimeError, ValueError, SubprocessError)


def catalog_client(config: dict) -> ReleaseCatalog:
    try:
        return configured_catalog(config)
    except (*_OBSERVATION_ERRORS, AttributeError):
        raise HTTPException(503, "DVT release catalog is not configured") from None


def catalog_router(
    config: dict, store: OperationStore, auth: CandidateAuth
) -> APIRouter:
    router = APIRouter(prefix="/api/releases")

    @router.get("", dependencies=[Depends(auth.operator_or_gateway)])
    def releases(channel: Literal["stable", "rc"] = "stable"):
        catalog = catalog_client(config)
        snapshot = catalog.refresh()
        source_error = None
        paths = {}
        try:
            observed = observe_source(config, store)
        except _OBSERVATION_ERRORS:
            source_error = "source_unconfirmed"
            observed = None
        else:
            if catalog.verify is not None:
                paths = catalog.paths(snapshot, observed, allow_rc=channel == "rc")
        pin = initial_release(config) if observed is None and source_error is None else None
        matching = [
            row for row in reversed(snapshot.releases)
            if row.channel == channel and row.version in paths
            and (pin is None or (row.version, row.manifest_digest) == (pin.version, pin.manifest_digest))
        ]
        return {
            "catalog_fetched_at": snapshot.fetched_at,
            "catalog_error": snapshot.error,
            "source_error": source_error,
            "source": observed,
            "trust_configured": catalog.verify is not None,
            "releases": matching,
            "recommended_stable": matching[0] if matching and channel == "stable" else None,
            "paths": {row.version: [step.version for step in paths[row.version]] for row in matching},
            "first_steps": {row.version: paths[row.version][0] for row in matching},
        }

    @router.post("/selection", dependencies=[Depends(auth.require_operator)])
    def select(selection: Selection):
        return select_release(config, store, selection)[0]

    return router


def select_release(config, store, selection):
    catalog = catalog_client(config)
    if catalog.verify is None:
        raise HTTPException(503, "DVT release trust is not configured")
    snapshot = catalog.refresh()
    version = version_tag(selection.version)
    entry = next((
        row for row in snapshot.releases
        if row.version == version and row.manifest_digest == selection.manifest_digest
    ), None)
    if entry is None:
        if snapshot.error:
            raise HTTPException(503, "No cached matching DVT release is available")
        raise HTTPException(404, "No matching DVT release is available")
    try:
        observed = observe_source(config, store)
    except _OBSERVATION_ERRORS:
        raise HTTPException(409, "The current release and schema are not established") from None
    if observed is None:
        pin = initial_release(config)
        if pin and (version, entry.manifest_digest) != (pin.version, pin.manifest_digest):
            raise HTTPException(409, "The selected release differs from the initial installation pin")
    try:
        return catalog.select(entry, observed, allow_rc=selection.confirm_rc), observed
    except StagingError as error:
        response_code = 422
        if error.reason in {FailureReason.DISTRIBUTOR_UNAVAILABLE, FailureReason.TLS}:
            response_code = 503
        raise HTTPException(response_code, {"reason": error.reason.value}) from None
    except OSError:
        raise HTTPException(503, "The protected catalog cache is unavailable") from None
