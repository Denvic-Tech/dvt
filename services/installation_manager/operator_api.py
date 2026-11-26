"""The operator browser facade over the protected catalog, journal and executor."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from hashlib import sha256
from pathlib import Path
from subprocess import SubprocessError
from typing import Annotated
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from core.operator_contract import (
    ActionConfirmation,
    BrowserPairing,
    InstallRequest,
    OperationPlan,
    OperationView,
    PairingCode,
    UpdateRequest,
)

from .application.first_install import (
    INTENT,
    MAX_INTENT_BYTES,
    normalized_request,
    pending_intent,
    request_directory,
)
from .application.maintenance_backup import DRAIN_SECONDS
from .application.offline_bundles import _configuration
from .application.online_operations import initial_settings, is_online
from .application.recovery import Action, last_failure
from .catalog_api import initial_release, select_release
from .domain.operation_state import (
    ArtifactKind,
    FailureReason,
    OperationConflict,
    OperationKind,
    OperationRequest,
    OperationStage,
    OwnershipConflict,
)
from .domain.release_manifest import StagingError, canonical_json, strict_json
from .host_bootstrap import CONTROL, atomic_write, prepare_route_executor
from .infrastructure.operation_files import executor_lock
from .infrastructure.staging_artifacts import read_artifact, save_config, write_artifact
from .infrastructure.staging_commands import Deadline, RetryPolicy
from .infrastructure.staging_docker import StagingDocker

Admission = Annotated[InstallRequest | UpdateRequest, Field(discriminator="kind")]
LIMIT = 256 * 1024


class InstallerStatus(BaseModel):
    instance_id: UUID
    app_origin: str
    app_port: int
    install_dir: str
    install_dir_editable: bool
    public_urls: list[str]
    installed: bool
    setup_required: bool
    initial_release_version: str | None = None
    setup_operation_id: UUID | None
    ui_version: str


def _conflict(operation_id: UUID) -> HTTPException:
    return HTTPException(
        409, {"operation_id": str(operation_id)},
        headers={"Location": f"/api/operator/operations/{operation_id}"},
    )


def _marker(store, operation):
    if not is_online(store, operation):
        path = store.artifact_path(ArtifactKind.STAGING, operation.id) / "legacy-import.json"
        raw = read_artifact(path, LIMIT)
        if raw is None:
            return None
        imported = strict_json(raw)
        return {"kind": "update", "version": imported["target_version"],
                "manifest_digest": imported["target_manifest_digest"]}
    path = store.artifact_path(ArtifactKind.CONFIG, operation.request.config_id)
    return strict_json(read_artifact(path / "operator.json", MAX_INTENT_BYTES))


def _plan(store, operation) -> OperationPlan | None:
    if operation.observation.staging_id != operation.id:
        return None
    directory = store.artifact_path(ArtifactKind.STAGING, operation.id)
    raw = read_artifact(directory / "plan.json", LIMIT)
    if raw is None:
        return None
    plan = strict_json(raw)
    raw_manifest = read_artifact(directory / "manifest.json", LIMIT)
    if raw_manifest is None:
        return None
    manifest = strict_json(raw_manifest)["payload"]
    platform = manifest["platforms"][plan["platform"]]
    active_images = set(plan["services"].values())
    image_sizes: dict[str, int] = {}
    for image in platform["images"].values():
        reference = image["reference"]
        if reference in active_images:
            size = image["compressed_bytes"] + image["unpacked_bytes"]
            image_sizes[reference] = max(image_sizes.get(reference, 0), size)
    base = manifest["environment"]["base"]
    profiles = [
        base, *(manifest["environment"]["profiles"][name] for name in plan["profiles"]),
    ]
    return OperationPlan(
        source_version=plan["observed_version"], source_revision=plan["observed_revision"],
        target_revision=plan["target_revision"], add=plan["add"], recreate=plan["recreate"],
        retire=plan["retire"], profiles=plan["profiles"],
        migration=plan["transition"]["migration"] if plan["transition"] else None,
        rollback=plan["transition"]["rollback"] if plan["transition"] else None,
        target_version=manifest["version"],
        pull_and_unpack_bytes=sum(image_sizes.values()),
        data_reserve_bytes=max(profile["data_reserve_bytes"] for profile in profiles),
        maintenance_drain_seconds=DRAIN_SECONDS,
        schedule_policy="skip_cron_preserve_existing_retries",
        queue_policy="drain_admitted_cancel_unadmitted_roots",
    )


def operator_router(config, store, auth, snapshot, start, diagnostics, static_dir) -> APIRouter:
    async def finish_first_install():
        while True:
            try:
                intent = pending_intent(control)
                if intent is None:
                    return
                payload = InstallRequest.model_validate(intent["request"])
                await asyncio.to_thread(admit_operation, payload, intent["key"], False)
            except HTTPException as error:
                if error.status_code != 503:
                    logging.getLogger(__name__).warning(
                        "First install admission returned HTTP %s", error.status_code,
                    )
                    return
                await asyncio.sleep(2)
            else:
                (control / INTENT).unlink(missing_ok=True)
                return

    @asynccontextmanager
    async def lifespan(_app):
        task = None
        if not config.get("wizard_temporary") and (control / INTENT).is_file():
            task = asyncio.create_task(finish_first_install())
        try:
            yield
        finally:
            if task is not None:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    router = APIRouter(prefix="/api/operator", lifespan=lifespan)
    directory = Path(config["data"])
    control = directory / CONTROL
    operator = [Depends(auth.operator_or_gateway)]
    paired = [Depends(auth.require_operator)]
    gateway = [Depends(auth.require_gateway)]
    index = static_dir / "index.html" if static_dir else None
    version = sha256(index.read_bytes()).hexdigest() if index and index.is_file() else "bootstrap"

    def scoped(request: Request, operation):
        if getattr(request.state, "gateway_operator", False) and (
            operation.request.kind is not OperationKind.UPDATE
        ):
            raise HTTPException(404, "Unknown update operation")
        return operation

    def lookup(request: Request, operation_id: UUID):
        operation = store.current_step(operation_id)
        if operation is None:
            raise HTTPException(404, "Unknown operation")
        return scoped(request, operation)

    def view(operation) -> OperationView:
        marker = _marker(store, operation)
        failure = last_failure(store.recent_events(operation.id), stage=operation.stage)
        if failure is None and (initial_failure := store.first_failure(operation.id)):
            failure = initial_failure.checkpoint.reason if operation.stage.terminal else None
        actions = snapshot(operation).actions
        if not operation.stage.terminal:
            directory = store.artifact_path(ArtifactKind.STAGING, operation.id)
            if failure is None and (directory / "launch-failed").is_file():
                failure = "executor_unavailable"
            if not actions and (directory / "restored-data.json").is_file():
                actions = [Action.RESTORE_START]
        if (
            marker and Action.CANCEL_PREPARATION in actions
            and operation.stage in {OperationStage.ADMITTED, OperationStage.PREPARING}
        ):
            actions = [Action.RESUME, *actions]
        if actions and store.executor_busy():
            actions = []
        plan = _plan(store, operation)
        root = store.get(store.route_root(operation.id))
        return OperationView(
            id=root.id, kind=operation.request.kind,
            version=(
                marker["version"] if marker else
                plan.target_version if plan else operation.request.release.release_id
            ),
            manifest_digest=marker["manifest_digest"] if marker else operation.request.release.manifest_digest,
            stage=operation.stage,
            failure=failure, actions=actions, plan=plan,
            created_at=root.admitted_at, finished_at=operation.finished_at,
        )

    def install_operation(operation_id: UUID):
        operation = store.get(operation_id)
        applied = read_artifact(control / "current-release.json", LIMIT)
        if (
            operation is None or operation.request.kind is not OperationKind.INSTALL
            or operation.stage is not OperationStage.SUCCEEDED or applied is None
            or strict_json(applied)["operation"] != str(operation_id)
        ):
            raise HTTPException(409, "Setup requires a ready installation")
        return operation

    def completed(operation_id: UUID) -> bool:
        return read_artifact(control / "setup-completed", 36) == str(operation_id).encode()

    @router.get("/settings", dependencies=paired)
    def settings() -> InstallerStatus:
        origin = config["public_url"]
        parsed = urlsplit(origin)
        applied = read_artifact(control / "current-release.json", LIMIT)
        requires_setup = False
        operation = None
        if applied is not None:
            operation_id = UUID(strict_json(applied)["operation"])
            operation = store.get(operation_id)
            requires_setup = bool(
                operation and operation.request.kind is OperationKind.INSTALL
                and operation.stage is OperationStage.SUCCEEDED and not completed(operation_id)
            )
        pin = initial_release(config) if applied is None else None
        return InstallerStatus(
            install_dir=config.get("default_install_dir", "/var/lib/dvt") if config.get("wizard_temporary")
            else config["data"],
            install_dir_editable=bool(config.get("wizard_temporary")),
            public_urls=config.get("public_urls") or [origin],
            instance_id=config["instance"],
            initial_release_version=pin.version if pin else None,
            app_origin=origin, app_port=parsed.port or (443 if parsed.scheme == "https" else 80),
            installed=applied is not None and operation is not None and operation.stage.terminal,
            setup_required=requires_setup,
            setup_operation_id=operation.id if requires_setup else None,
            ui_version=version,
        )

    @router.post("/operations", status_code=202, dependencies=operator)
    def admit(
        request: Request, payload: Admission, key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> OperationView:
        return admit_operation(payload, key, getattr(request.state, "gateway_operator", False))

    def admit_operation(payload: InstallRequest | UpdateRequest, key: str, gateway_request: bool):
        if gateway_request and payload.kind != "update":
            raise HTTPException(403, "Gateway may only admit updates")
        if isinstance(payload, InstallRequest):
            payload = normalized_request(payload, config)
        intent = payload.model_dump(mode="json", exclude_none=True)
        # Keep the nullable port in the on-disk intent used by older clients.
        if isinstance(payload, InstallRequest):
            intent["app_port"] = payload.app_port
        try:
            with executor_lock(control / "operator-admission.lock"):
                existing = store.by_idempotency_key(key)
                if existing is not None:
                    if gateway_request and existing.request.kind is not OperationKind.UPDATE:
                        raise HTTPException(404, "Unknown update operation")
                    previous = _marker(store, existing)
                    if (
                        isinstance(payload, InstallRequest)
                        and "task_workers_count" not in payload.model_fields_set
                        and previous and "install_dir" not in previous
                        and previous.get("task_workers_count") == 1
                    ):
                        # Older clients could rely on the former default of one worker.
                        intent["task_workers_count"] = 1
                    if previous != intent:
                        raise _conflict(existing.id)
                    operation = store.current_step(existing.id) or existing
                elif active := store.active():
                    raise _conflict(store.route_root(active.id))
                else:
                    selected, source = select_release(config, store, payload)
                    if (payload.kind == "install") != (source is None):
                        raise HTTPException(409, "The action does not match the observed installation")
                    if config.get("wizard_temporary"):
                        request_directory(control, key, intent)
                    if isinstance(payload, InstallRequest):
                        values = initial_settings()
                        if payload.public_urls:
                            values["DVT_PUBLIC_URL"] = ";".join(payload.public_urls)
                        if any(urlsplit(url).scheme == "https" for url in
                               (payload.public_urls or [config["public_url"]])):
                            values["DVT_COOKIE_SECURE"] = "true"
                        default_port = settings().app_port
                        operation_settings = {
                            "app_port": payload.app_port or default_port,
                            "task_workers_count": payload.task_workers_count,
                            "ai_mcp_enabled": payload.ai_mcp_enabled,
                        }
                    else:
                        if settings().setup_required:
                            raise HTTPException(409, "Complete the initial setup before updating")
                        local = StagingDocker(directory, control / "docker")
                        observed, values = _configuration(
                            config, store, Deadline(RetryPolicy(), Path(config["temporary"])), local,
                        )
                        if (observed.version, observed.revision) != (source.version, source.revision):
                            raise HTTPException(409, "The observed source changed")
                        if selected.following and not prepare_route_executor(config):
                            raise StagingError(
                                FailureReason.INCOMPATIBLE_RELEASE,
                                "The installed executor cannot continue a release route",
                                "Install a compatible manager through a supported direct update",
                            )
                        operation_settings = {}
                    values["DVT_ALLOW_PRERELEASE"] = "true" if payload.confirm_rc else "false"
                    config_id = save_config(store, values)
                    saved = store.artifact_path(ArtifactKind.CONFIG, config_id)
                    write_artifact(saved / "operator.json", canonical_json(intent))
                    operation = store.admit(
                        OperationRequest(
                            OperationKind(payload.kind), selected.pin, config_id=config_id,
                            **operation_settings,
                        ),
                        idempotency_key=key,
                        following=selected.following if isinstance(payload, UpdateRequest) else (),
                    )
        except OperationConflict as error:
            raise _conflict(error.operation_id) from None
        except OwnershipConflict:
            active = store.active()
            existing = store.by_idempotency_key(key) if active else None
            if active and (existing is None or active.id != existing.id):
                raise _conflict(active.id) from None
            raise HTTPException(503, "Another request is selecting a release") from None
        except StagingError as error:
            raise HTTPException(422, {"reason": error.reason.value}) from None
        except (OSError, SubprocessError):
            raise HTTPException(503, "Unable to validate the saved instance configuration") from None
        except ValueError:
            raise HTTPException(422, "Invalid operation fields or idempotency key") from None
        if operation.stage in {OperationStage.ADMITTED, OperationStage.PREPARING}:
            operation = start(operation).operation
        return view(operation)

    @router.get("/update-summary", dependencies=gateway)
    def update_summary():
        active = store.active()
        if active is not None:
            if active.request.kind is not OperationKind.UPDATE:
                return None
            if store.route_root(active.id) == active.id and active.stage in {
                OperationStage.ADMITTED, OperationStage.PREPARING, OperationStage.PREPARED,
            } and not (store.artifact_path(ArtifactKind.STAGING, active.id) / "legacy-import.json").is_file():
                return None
            operation = active
            state = "running"
        else:
            operation = next((
                row for row in store.history(limit=20)
                if row.request.kind is OperationKind.UPDATE
            ), None)
            if operation is None or operation.stage not in {
                OperationStage.SUCCEEDED, OperationStage.CANCELLED,
            }:
                return None
            # Both successful application and a verified cancellation restore service readiness.
            state = "succeeded"
        root = store.get(store.route_root(operation.id))
        marker = _marker(store, operation)
        return {
            "id": root.id, "kind": operation.request.kind, "state": state,
            "version": marker["version"] if marker else operation.request.release.release_id,
            "started_at": root.admitted_at,
            "finished_at": operation.finished_at,
        }

    @router.get("/operations/active", dependencies=operator)
    def active(request: Request) -> OperationView | None:
        operation = store.active()
        if operation and (
            not getattr(request.state, "gateway_operator", False)
            or operation.request.kind is OperationKind.UPDATE
        ):
            return view(operation)
        return None

    @router.get("/operations", dependencies=operator)
    def history(
        request: Request, limit: int = Query(default=20, ge=1, le=20),
    ) -> list[OperationView]:
        gateway_request = getattr(request.state, "gateway_operator", False)
        records = []
        seen = set()
        before = None
        for _ in range(5):
            page = store.history(before=before, limit=20)
            for row in page:
                if gateway_request and row.request.kind is not OperationKind.UPDATE:
                    continue
                root_id = store.route_root(row.id)
                if root_id not in seen:
                    records.append(row)
                    seen.add(root_id)
            if len(records) >= limit or len(page) < 20:
                break
            before = page[-1].id
        return [view(row) for row in records[:limit]]

    @router.get("/operations/{operation_id}", dependencies=operator)
    def get(request: Request, operation_id: UUID) -> OperationView:
        return view(lookup(request, operation_id))

    @router.post("/operations/{operation_id}/actions/{action}", status_code=202, dependencies=operator)
    def act(
        request: Request, operation_id: UUID, action: Action, confirmation: ActionConfirmation,
    ) -> OperationView:
        operation = lookup(request, operation_id)
        if action not in view(operation).actions:
            raise HTTPException(409, "This action is not available")
        if getattr(request.state, "gateway_operator", False) and action is Action.RESTORE_START:
            raise HTTPException(403, "Authorize the verified restore in the independent manager")
        if action in {Action.APPLY, Action.RETURN_TO_SOURCE, Action.RESTORE_START} and not confirmation.confirm:
            raise HTTPException(422, "This action requires explicit confirmation")
        operation = start(operation, action).operation
        return view(operation)

    @router.get("/operations/{operation_id}/log", dependencies=operator)
    def operation_log(
        request: Request, operation_id: UUID, after: int = Query(0, ge=0, lt=2**63),
        limit: int = Query(100, ge=1, le=100),
    ):
        lookup(request, operation_id)
        lines = store.log_lines(operation_id, after=after, limit=limit)
        return {"lines": lines, "next_cursor": lines[-1]["cursor"] if lines else after}

    @router.get("/operations/{operation_id}/diagnostics", dependencies=operator)
    def support(request: Request, operation_id: UUID, after: int = 0) -> dict:
        operation = lookup(request, operation_id)
        if not 0 <= after < 2**63:
            raise HTTPException(422, "Invalid diagnostic cursor")
        return diagnostics(operation.id, after=after, limit=100)

    @router.post("/setup/{operation_id}/pairing", dependencies=paired)
    def setup_link(operation_id: UUID) -> PairingCode:
        install_operation(operation_id)
        if completed(operation_id):
            raise HTTPException(409, "Setup is already completed")
        try:
            return PairingCode(code=auth.issue_setup(operation_id))
        except OwnershipConflict:
            raise HTTPException(409, "Setup pairing is in progress") from None

    @router.post("/setup/{operation_id}/exchange", dependencies=gateway)
    def setup_exchange(operation_id: UUID, pairing: BrowserPairing) -> None:
        install_operation(operation_id)
        if completed(operation_id):
            raise HTTPException(409, "Setup is already completed")
        try:
            auth.consume_setup(operation_id, pairing.code.get_secret_value())
        except OwnershipConflict:
            raise HTTPException(409, "Setup pairing is in progress") from None

    @router.post("/setup/{operation_id}/complete", dependencies=gateway)
    def setup_complete(operation_id: UUID) -> None:
        install_operation(operation_id)
        atomic_write(control / "setup-completed", str(operation_id).encode())

    return router
