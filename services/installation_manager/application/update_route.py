"""Continue a legacy UI request with ordinary managed update operations."""

from uuid import UUID

from ..catalog_api import configured_catalog
from ..domain.operation_state import ArtifactKind
from ..domain.release_manifest import canonical_json
from ..infrastructure.staging_artifacts import save_config, write_artifact
from ..infrastructure.staging_host import incompatible
from .legacy_baseline import BASELINE
from .release_catalog import SourceFacts


def attach_legacy_route(
    config, store, baseline_operation, target_version, target_manifest_digest, values,
):
    """Pin all signed steps before switching the source database or application."""
    if baseline_operation.request.release != BASELINE:
        raise ValueError("The import journal does not match the requested legacy job")
    if target_version == "1.24.0":
        if target_manifest_digest != BASELINE.manifest_digest:
            raise incompatible("The requested 1.24.0 package differs from the imported release")
        return
    pinned = store.route_target(baseline_operation.id)
    if pinned is not None:
        if pinned.manifest_digest != target_manifest_digest:
            raise incompatible("The pinned route differs from the original request")
        return
    catalog = configured_catalog(config)
    snapshot = catalog.refresh()
    target = next((
        row for row in snapshot.releases
        if row.version == target_version and row.manifest_digest == target_manifest_digest
    ), None)
    if target is None or target.channel != "stable":
        raise incompatible("The requested stable release is unavailable")
    selected = catalog.select_route(snapshot, target, SourceFacts("1.24.0", "0070"))
    config_id = save_config(store, values)
    directory = store.artifact_path(ArtifactKind.CONFIG, config_id)
    write_artifact(directory / "operator.json", canonical_json({
        "kind": "update", "version": target_version, "manifest_digest": target_manifest_digest,
        "confirm_rc": False,
    }))
    store.attach_route(baseline_operation.id, (selected.pin, *selected.following), config_id)


def continue_legacy_update(config, store, operation_id: UUID) -> None:
    """A resumed import and a live importer both follow the same durable step ID."""
    from ..candidate_executor import execute

    step = store.current_step(operation_id)
    if step is None:
        raise ValueError("The legacy update job is missing")
    if step.id != operation_id and not step.stage.terminal:
        execute(config, store, step.id)
