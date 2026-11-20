"""Authenticated API for the opt-in bootstrap and manager handoff."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from .application.recovery import (
    Action,
    actions,
    last_failure,
    read_observation,
    read_source_failure,
    restore_actions,
)
from .candidate_auth import SESSION_TTL, CandidateAuth
from .catalog_api import catalog_router
from .domain.operation_state import (
    ArtifactKind,
    Operation,
    OperationConflict,
    OperationEvent,
    OperationKind,
    OperationNotFound,
    OperationRequest,
    OwnershipConflict,
    ReleasePin,
)
from .host_bootstrap import candidate, launch
from .infrastructure.operation_store import FORMAT_VERSION, OperationStore
from .infrastructure.staging_artifacts import artifact_directory


class CandidatePin(BaseModel):
    model_config = ConfigDict(extra="forbid")
    release_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.+-]{0,127}$")]
    manifest_digest: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


class Admission(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["manager_recovery"]
    release: CandidatePin


class Pairing(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: Annotated[SecretStr, Field(min_length=43, max_length=43)]


class Snapshot(BaseModel):
    journal_format: Literal[1] = FORMAT_VERSION
    operation: Operation
    actions: list[Action]


def create_app(config: dict, store: OperationStore, static_dir: Path | None) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    auth = CandidateAuth(config)
    pin = ReleasePin(*candidate(config))
    operator = [Depends(auth.require_operator)]

    @app.middleware("http")
    async def set_response_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'"
        )
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request: Request, _error: RequestValidationError):
        return JSONResponse({"detail": "Invalid request fields"}, status_code=422)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/session", dependencies=[Depends(auth.csrf)])
    def pair(data: Pairing, response: Response) -> dict[str, str]:
        try:
            cookie = auth.pair(data.code.get_secret_value())
        except OwnershipConflict:
            raise HTTPException(409, "Pairing in progress") from None
        response.set_cookie(
            auth.cookie,
            cookie,
            max_age=SESSION_TTL,
            httponly=True,
            secure=auth.secure,
            samesite="strict",
        )
        return {"status": "paired"}

    def snapshot(operation: Operation) -> Snapshot:
        failure = (
            last_failure(store.recent_events(operation.id), stage=operation.stage)
            if not operation.stage.terminal
            and operation.request.kind is not OperationKind.MANAGER_RECOVERY
            else None
        )
        available = restore_actions(store, operation)
        if available is None:
            available = actions(operation, failure)
        return Snapshot(operation=operation, actions=available)

    def lookup(operation_id: UUID) -> Operation:
        operation = store.get(operation_id)
        if operation is None:
            raise HTTPException(404, "Unknown operation")
        return operation

    def start(operation: Operation, action: Action = Action.RESUME) -> Snapshot:
        if not operation.stage.terminal:
            try:
                if action is Action.RESUME:
                    launch(config, str(operation.id))
                else:
                    command = {
                        Action.CANCEL_PREPARATION: "candidate-cancel-preparation",
                        Action.APPLY: "candidate-maintenance",
                        Action.RESTORE_START: "candidate-restore-start",
                        Action.EXTEND_MAINTENANCE: "candidate-maintenance-extend",
                        Action.DEFER_MAINTENANCE: "candidate-maintenance-defer",
                        Action.RECOVER_MANAGER: "candidate-recover-manager",
                        Action.RETURN_TO_SOURCE: "candidate-return-to-source",
                    }[action]
                    launch(config, str(operation.id), command)
            except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
                if action is not Action.RESUME:
                    raise HTTPException(409, "The executor could not accept the action") from None
                if operation.request.kind is OperationKind.INSTALL:
                    directory = artifact_directory(store, ArtifactKind.STAGING, operation.id)
                    (directory / "launch-failed").touch(mode=0o600)
                    store.log_message(operation.id, "Не удалось запустить исполнитель установки")
                # The operation remains committed and is resumable by ID or at boot.
                return snapshot(operation)
            if operation.request.kind is OperationKind.INSTALL:
                (store.artifact_path(ArtifactKind.STAGING, operation.id) / "launch-failed").unlink(
                    missing_ok=True,
                )
        return snapshot(store.get(operation.id) or operation)

    @app.get("/api/operations/candidate", dependencies=operator)
    def plan() -> CandidatePin:
        return CandidatePin(release_id=pin.release_id, manifest_digest=pin.manifest_digest)

    @app.post("/api/operations", status_code=202, dependencies=operator)
    def admit(data: Admission, key: Annotated[str, Header(alias="Idempotency-Key")]) -> Snapshot:
        if config.get("wizard_temporary"):
            raise HTTPException(409, "Сначала укажите параметры установки.")
        release = ReleasePin(data.release.release_id, data.release.manifest_digest)
        if release != pin:
            raise HTTPException(422, "The request does not select the approved candidate")
        try:
            operation = store.admit(
                OperationRequest(OperationKind(data.kind), release),
                idempotency_key=key,
            )
        except OperationConflict as error:
            raise HTTPException(
                409,
                {"operation_id": str(error.operation_id)},
                headers={"Location": f"/api/operations/{error.operation_id}"},
            ) from None
        except ValueError:
            raise HTTPException(422, "Invalid idempotency key") from None
        return start(operation)

    @app.get("/api/operations/active", dependencies=operator)
    def active() -> Snapshot | None:
        operation = store.active()
        return snapshot(operation) if operation else None

    @app.get("/api/operations", dependencies=operator)
    def history(
        before: UUID | None = None,
        limit: int = Query(default=20, ge=1, le=100),
    ) -> list[Snapshot]:
        try:
            return [snapshot(operation) for operation in store.history(before=before, limit=limit)]
        except OperationNotFound:
            raise HTTPException(404, "Unknown history cursor") from None

    @app.get("/api/operations/{operation_id}", dependencies=operator)
    def get(operation_id: UUID) -> Snapshot:
        return snapshot(lookup(operation_id))

    @app.post("/api/operations/{operation_id}/resume", status_code=202, dependencies=operator)
    def resume(operation_id: UUID) -> Snapshot:
        operation = lookup(operation_id)
        if operation.stage.terminal:
            return snapshot(operation)
        return operate(operation_id, Action.RESUME)

    @app.post(
        "/api/operations/{operation_id}/actions/{action}", status_code=202, dependencies=operator,
    )
    def operate(operation_id: UUID, action: Action) -> Snapshot:
        if action in {Action.APPLY, Action.RETURN_TO_SOURCE, Action.RESTORE_START}:
            raise HTTPException(409, "Use the confirmed action in the operator API")
        operation = lookup(operation_id)
        if action not in snapshot(operation).actions:
            raise HTTPException(409, "The action is not available at the current stage")
        return start(operation, action)

    @app.get("/api/operations/{operation_id}/diagnostics", dependencies=operator)
    def diagnostics(
        operation_id: UUID,
        after: int = Query(default=0, ge=0, lt=2**63),
        limit: int = Query(default=50, ge=1, le=100),
    ):
        operation = lookup(operation_id)
        return {
            "format_version": 1,
            "snapshot": snapshot(operation),
            "observation": read_observation(store, operation_id),
            "first_failure": store.first_failure(operation_id),
            "source_failure": read_source_failure(store, operation_id),
            "events": store.events(operation_id, after=after, limit=limit),
        }

    @app.get("/api/operations/{operation_id}/events", dependencies=operator)
    def events(
        operation_id: UUID,
        after: int = Query(default=0, ge=0, lt=2**63),
        limit: int = Query(default=100, ge=1, le=100),
    ) -> list[OperationEvent]:
        lookup(operation_id)
        return store.events(operation_id, after=after, limit=limit)

    from .operator_api import operator_router

    app.include_router(catalog_router(config, store, auth))
    app.include_router(operator_router(config, store, auth, snapshot, start, diagnostics, static_dir))

    @app.api_route("/api/{path:path}", methods=["GET", "POST"], dependencies=operator)
    @app.post("/update", dependencies=operator)
    def legacy(path: str = "") -> None:  # noqa: ARG001 - legacy path is intentionally unused
        raise HTTPException(410, "Use the authenticated operation API for this instance")

    if static_dir is not None and static_dir.is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
    return app
