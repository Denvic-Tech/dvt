from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from httpx import Response

from services.gateway.update_runtime import (
    get_installation_manager_client,
    get_system_state_monitor,
)
from services.gateway.update_runtime.client import (
    InstallationManagerHTTPError,
    InstallationManagerUnavailable,
)

from src.modules.user.infra.fastapi.dependencies import UserSuperadminAccessOnly
from src.schemas.http.update import (
    UpdateRequestSchema,
    UpdateResponseSchema,
    UpdateStatusSchema,
)

router = APIRouter(prefix="/update", tags=["Update"])


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


@router.post("/run", response_model=UpdateResponseSchema)
async def run_update(
    data: UpdateRequestSchema,
    user: UserSuperadminAccessOnly,  # noqa: ARG001
) -> UpdateResponseSchema:
    response = await _installation_manager_request(
        "POST",
        "/update",
        json={"version": data.version},
    )
    result = UpdateResponseSchema.model_validate(response.json())
    await get_system_state_monitor().mark_updating(result.job_id)
    return result


@router.get("/status", response_model=UpdateStatusSchema)
async def update_status(
    user: UserSuperadminAccessOnly,  # noqa: ARG001
    log_offset: int = Query(default=0, ge=0),
) -> UpdateStatusSchema:
    response = await _installation_manager_request(
        "GET", "/api/jobs/current", params={"log_offset": log_offset}
    )
    return UpdateStatusSchema.model_validate(response.json())
