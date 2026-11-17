from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from httpx import Response
from pydantic import BaseModel
from starlette.responses import JSONResponse

from core.operator_contract import (
    ActionConfirmation,
    CatalogView,
    OperationView,
    OperatorAction,
    UpdateRequest,
)

from services.gateway.update_runtime import (
    get_installation_manager_client,
    get_system_state_monitor,
)
from services.gateway.update_runtime.client import (
    InstallationManagerHTTPError,
    InstallationManagerUnavailable,
)
from services.gateway.update_runtime.operator import (
    manager_origin,
    operator_request,
    require_browser_origin,
)

from src.modules.user.infra.fastapi.dependencies import UserSuperadminAccessOnly
from src.schemas.http.update import (
    UpdateRequestSchema,
    UpdateResponseSchema,
    UpdateStatusSchema,
)

router = APIRouter(prefix="/update", tags=["Update"])
browser_mutation = [Depends(require_browser_origin)]
path = "/api/operator/operations"


class ManagerAccess(BaseModel):
    origin: str | None


async def _installation_manager_request(method: str, path: str, **kwargs: Any) -> Response:
    try:
        return await get_installation_manager_client().request(method, path, **kwargs)
    except InstallationManagerUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="update-service unreachable",
        ) from exc
    except InstallationManagerHTTPError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


async def _latest_operation() -> OperationView | None:
    response = await operator_request("GET", f"{path}/active")
    data = response.json()
    if data is None:
        response = await operator_request("GET", path)
        data = next(iter(response.json()), None)
    return OperationView.model_validate(data) if data is not None else None


@router.post("/run", response_model=UpdateResponseSchema)
async def run_update(
    data: UpdateRequestSchema,
    user: UserSuperadminAccessOnly,  # noqa: ARG001
) -> UpdateResponseSchema:
    if manager_origin():
        operation = await _latest_operation()
        if operation and operation.version == data.version:
            return UpdateResponseSchema(
                success=False, message="Read the protected operation state by ID",
                job_id=str(operation.id), version=operation.version,
            )
        raise HTTPException(410, "Select and prepare an immutable release from the update page")
    response = await _installation_manager_request(
        "POST", "/update", json={"version": data.version},
    )
    result = UpdateResponseSchema.model_validate(response.json())
    await get_system_state_monitor().mark_updating(result.job_id)
    return result


@router.get("/status", response_model=UpdateStatusSchema)
async def update_status(
    user: UserSuperadminAccessOnly,  # noqa: ARG001
    log_offset: int = Query(default=0, ge=0),
) -> UpdateStatusSchema:
    if manager_origin():
        result = await _latest_operation()
        if result is None:
            raise HTTPException(404, "No protected update operation")
        state = result.stage
        return UpdateStatusSchema(
            id=str(result.id), kind=result.kind, version=result.version, error=result.failure,
            state=state if state in {"succeeded", "failed", "cancelled"} else "running",
            started_at=result.created_at.isoformat(),
            finished_at=result.finished_at.isoformat() if result.finished_at else None,
            steps=[], log=[], log_total=0,
        )
    response = await _installation_manager_request(
        "GET", "/api/jobs/current", params={"log_offset": log_offset}
    )
    return UpdateStatusSchema.model_validate(response.json())


@router.get("/manager")
async def get_update_manager(user: UserSuperadminAccessOnly) -> ManagerAccess:  # noqa: ARG001
    return ManagerAccess(origin=manager_origin())


@router.get("/releases")
async def get_update_releases(
    user: UserSuperadminAccessOnly,  # noqa: ARG001
    channel: Literal["stable", "rc"] = "stable",
) -> CatalogView:
    response = await operator_request("GET", "/api/releases", params={"channel": channel})
    return CatalogView.model_validate(response.json())


@router.post("/operations", status_code=202, response_model=OperationView, dependencies=browser_mutation)
async def create_update_operation(
    data: UpdateRequest,
    key: Annotated[str, Header(alias="Idempotency-Key")],
    user: UserSuperadminAccessOnly,  # noqa: ARG001
) -> OperationView | Response:
    try:
        result = await operator_request(
            "POST", path, json=data.model_dump(mode="json"), headers={"Idempotency-Key": key},
        )
    except HTTPException as error:
        return JSONResponse(status_code=error.status_code, content={"detail": error.detail})
    return OperationView.model_validate(result.json())


@router.get("/operations/active")
async def get_active_update(user: UserSuperadminAccessOnly) -> OperationView | None:  # noqa: ARG001
    response = await operator_request("GET", f"{path}/active")
    data = response.json()
    return OperationView.model_validate(data) if data is not None else None


@router.get("/operations")
async def get_update_history(user: UserSuperadminAccessOnly) -> list[OperationView]:  # noqa: ARG001
    response = await operator_request("GET", path)
    return [OperationView.model_validate(value) for value in response.json()]


@router.get("/operations/{operation_id}")
async def get_update_operation(
    operation_id: UUID, user: UserSuperadminAccessOnly,  # noqa: ARG001
) -> OperationView:
    response = await operator_request("GET", f"{path}/{operation_id}")
    return OperationView.model_validate(response.json())


@router.post(
    "/operations/{operation_id}/actions/{action}", status_code=202, dependencies=browser_mutation,
)
async def act_on_update_operation(
    operation_id: UUID,
    action: OperatorAction,
    data: ActionConfirmation,
    user: UserSuperadminAccessOnly,  # noqa: ARG001
) -> OperationView:
    response = await operator_request(
        "POST", f"{path}/{operation_id}/actions/{action}", json=data.model_dump(mode="json"),
    )
    return OperationView.model_validate(response.json())


@router.get("/operations/{operation_id}/diagnostics")
async def get_update_diagnostics(
    operation_id: UUID,
    user: UserSuperadminAccessOnly,  # noqa: ARG001
    after: int = Query(default=0, ge=0, lt=2**63),
) -> dict[str, Any]:
    response = await operator_request("GET", f"{path}/{operation_id}/diagnostics", params={"after": after})
    return response.json()
