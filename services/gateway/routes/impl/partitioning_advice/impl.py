from fastapi import APIRouter, HTTPException

from services.gateway.routes.utils.DDL.connection import resolve_ddl_connection

from src.modules.user.infra.fastapi.dependencies import UserAccessOnly

from .schemas import PartitioningAdviceRequest, PartitioningAdviceResponse
from .service import PartitioningAdviceError, suggest_read_partitioning

router = APIRouter(tags=["DB Connections"])


@router.post(
    "/{connection_id}/partitioning-advice",
    response_model=PartitioningAdviceResponse,
    summary="Profile partition-key candidates for ReadTableFromDBV3/ReadQueryFromDBV3",
)
async def get_partitioning_advice(
    connection_id: str,
    request: PartitioningAdviceRequest,
    user: UserAccessOnly,
) -> PartitioningAdviceResponse:
    resolved = await resolve_ddl_connection(connection_id, user)
    try:
        return await suggest_read_partitioning(resolved.connection_string, request)
    except PartitioningAdviceError as exc:
        raise HTTPException(
            status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}
        ) from exc
