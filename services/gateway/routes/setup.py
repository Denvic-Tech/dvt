import contextlib
import hashlib
import hmac
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from pydantic import Field
from sqlalchemy import text
from starlette.responses import JSONResponse

from core.operator_contract import BrowserPairing

from services.gateway.update_runtime.operator import (
    manager_origin,
    operator_request,
    require_browser_origin,
)

from src import setup
from src.db import AsyncSession
from src.db.fastapi.dependencies import AsyncSessionDepends
from src.setup import SetupConflictError, SetupValidationError
from src.setup.dsl import SetupStatus, SetupStepSubmitRequest
from src.utils.deployment_migrations import MigrationContext

import config

router = r = APIRouter(prefix="/setup", tags=["Setup"])

COOKIE = "dvt_setup"
SESSION_TTL = 900
COOKIE_PATH = "/api/setup"
_acknowledged_installations: set[UUID] = set()


class SetupPairing(BrowserPairing):
    operation_id: UUID = Field(strict=False)


def _setup_cookie_mac(payload: str) -> str:
    # Separate the setup session capability from manager authentication.
    key = Path("/run/dvt-operator/gateway-token").read_bytes()
    return hmac.new(key, f"DVT setup session v1 {payload}".encode(), hashlib.sha256).hexdigest()


def _setup_session(request: Request, operation_id: UUID) -> bool:
    value = request.cookies.get(COOKIE, "")
    try:
        target, expiry, signature = value.split(".")
        return (
            target == str(operation_id)
            and int(expiry) > time.time()
            and signature.isascii()
            and hmac.compare_digest(signature, _setup_cookie_mac(f"{target}.{expiry}"))
        )
    except ValueError:
        return False


def _deployment_id() -> UUID:
    deployment = MigrationContext.read()
    if deployment is None:
        raise HTTPException(503, "The installation operation is not established")
    return deployment.operation_id


async def _acknowledge_setup(operation_id: UUID) -> None:
    if operation_id in _acknowledged_installations:
        return
    with contextlib.suppress(HTTPException):
        await operator_request("POST", f"/api/operator/setup/{operation_id}/complete", timeout=5)
        _acknowledged_installations.add(operation_id)


def _map_setup_error(exc: Exception) -> HTTPException:
    if isinstance(exc, SetupConflictError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, SetupValidationError):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    raise exc


def _build_submit_handler(
    step_code: str,
) -> Callable[[SetupStepSubmitRequest, AsyncSession], Awaitable[SetupStatus]]:
    async def submit_setup_step(
        request: SetupStepSubmitRequest,
        session: AsyncSessionDepends,
        browser: Request,
    ) -> SetupStatus | Response:
        operation_id = None
        if manager_origin():
            require_browser_origin(browser)
            operation_id = _deployment_id()
            if not _setup_session(browser, operation_id):
                raise HTTPException(403, "Pair this browser using the installation manager")
            # Serialize first-user creation across tabs and Gateway workers.
            await session.execute(text("SELECT pg_advisory_xact_lock(466211998)"))
        try:
            result = await setup.submit_setup_step(
                session,
                step_code=step_code,
                values=request.values,
            )
        except (SetupConflictError, SetupValidationError) as exc:
            if isinstance(exc, SetupValidationError) and exc.fields:
                return JSONResponse(
                    status_code=422,
                    content={"detail": [
                        {"loc": ["body", "values", key], "msg": message, "type": "value_error"}
                        for key, message in exc.fields.items()
                    ]},
                )
            raise _map_setup_error(exc) from exc
        if operation_id is not None and result.initialized:
            await _acknowledge_setup(operation_id)
            response = JSONResponse(result.model_dump(mode="json", exclude={"steps"}))
            response.delete_cookie(COOKIE, path=COOKIE_PATH)
            return response
        return result

    submit_setup_step.__name__ = f"submit_setup_step_{step_code}"
    return submit_setup_step


@r.get("/status", response_model=SetupStatus)
async def get_setup_status(
    session: AsyncSessionDepends, request: Request, response: Response, background: BackgroundTasks,
) -> SetupStatus:
    if not manager_origin():
        return await setup.get_setup_status(session)
    response.headers["Cache-Control"] = "no-store"
    initialized = await setup.is_setup_initialized(session)
    if initialized:
        # A lost reply from the manager must not strand a completed setup.
        deployment = MigrationContext.read()
        if deployment and deployment.source is None:
            background.add_task(_acknowledge_setup, deployment.operation_id)
        return SetupStatus(initialized=True)
    if not _setup_session(request, _deployment_id()):
        return SetupStatus(initialized=False, pairing_required=True)
    return await setup.get_setup_status(session)


@r.post("/pairing", dependencies=[Depends(require_browser_origin)])
async def pair_setup(
    data: SetupPairing, response: Response, session: AsyncSessionDepends,
) -> SetupStatus:
    if not manager_origin():
        raise HTTPException(404, "Protected setup is not enrolled")
    operation_id = _deployment_id()
    if data.operation_id != operation_id:
        raise HTTPException(409, "The setup link belongs to a different operation")
    if await setup.is_setup_initialized(session):
        await _acknowledge_setup(operation_id)
        raise HTTPException(409, "Setup is already completed")
    await operator_request(
        "POST", f"/api/operator/setup/{operation_id}/exchange",
        json={"code": data.code.get_secret_value()},
    )
    payload = f"{operation_id}.{int(time.time()) + SESSION_TTL}"
    response.set_cookie(
        COOKIE, f"{payload}.{_setup_cookie_mac(payload)}", max_age=SESSION_TTL,
        path=COOKIE_PATH, httponly=True, samesite="strict",
        secure=config.GATEWAY.GATEWAY_COOKIE_SECURE,
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return await setup.get_setup_status(session)


for step_cls in setup.get_all_setup_steps():
    router.add_api_route(
        f"/{step_cls.CODE}",
        _build_submit_handler(step_cls.CODE),
        methods=["POST"],
        response_model=SetupStatus,
        status_code=status.HTTP_200_OK,
        summary=f"Submit setup step '{step_cls.TITLE}'",
    )
