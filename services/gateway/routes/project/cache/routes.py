from typing import Annotated

from fastapi import APIRouter, Depends

from services.gateway.deps import (
    PipelineCacheFacade,
    get_pipeline_cache_facade,
)
from services.gateway.deps.project import UserProjectByPath

from src.db.fastapi.dependencies import AsyncSessionDepends
from src.modules.user.infra.fastapi.dependencies import UserAccessOnly

from .helpers import (
    clear_data_cache,
    clear_metadata_cache,
)
from .schemas import (
    ClearProjectCacheRequest,
    ClearProjectCacheResponse,
    ClearProjectDataCacheRequest,
    ClearProjectDataCacheResponse,
    ClearProjectMetadataCacheRequest,
    ClearProjectMetadataCacheResponse,
)

router = APIRouter(tags=["Cache"])


@router.post("/clear", response_model=ClearProjectCacheResponse)
async def clear(
        payload: ClearProjectCacheRequest,

        session: AsyncSessionDepends,
        user: UserAccessOnly,
        project: UserProjectByPath,
        pipeline_cache: Annotated[PipelineCacheFacade, Depends(get_pipeline_cache_facade)],
) -> ClearProjectCacheResponse:

    data_clear_result = await clear_data_cache(
        project=project,
        pipeline_cache=pipeline_cache,
        node_ids=payload.node_ids,
    )

    metadata_clear_result = await clear_metadata_cache(
        session=session,
        user=user,
        project=project,
        pipeline_cache=pipeline_cache,
        node_ids=payload.node_ids,
        send_metadata_task=payload.send_metadata_task,
    )

    cleared_keys = [*data_clear_result.cleared_keys, *metadata_clear_result.cleared_keys]

    return ClearProjectMetadataCacheResponse(
        success=True,
        message="Cache entry invalidated successfully.",
        task_id=metadata_clear_result.task_id,
        cleared_keys=cleared_keys,
    )


@router.post("/clear/data", response_model=ClearProjectDataCacheResponse)
async def invalidate_node_metadata_cache(
        payload: ClearProjectDataCacheRequest,

        project: UserProjectByPath,
        pipeline_cache: Annotated[PipelineCacheFacade, Depends(get_pipeline_cache_facade)],
) -> ClearProjectDataCacheResponse:
    result = await clear_data_cache(
        project=project,
        pipeline_cache=pipeline_cache,
        node_ids=payload.node_ids,
    )

    return ClearProjectDataCacheResponse(
        success=True,
        message="Cache entry invalidated successfully.",
        cleared_keys=result.cleared_keys,
    )


@router.post("/clear/metadata", response_model=ClearProjectMetadataCacheResponse)
async def clear_metadata(
        payload: ClearProjectMetadataCacheRequest,

        session: AsyncSessionDepends,
        user: UserAccessOnly,
        project: UserProjectByPath,
        pipeline_cache: Annotated[PipelineCacheFacade, Depends(get_pipeline_cache_facade)],
) -> ClearProjectMetadataCacheResponse:

    result = await clear_metadata_cache(
        session=session,
        user=user,
        project=project,
        pipeline_cache=pipeline_cache,
        node_ids=payload.node_ids,
        send_metadata_task=payload.send_metadata_task,
    )

    return ClearProjectMetadataCacheResponse(
        success=True,
        message="Cache entry invalidated successfully.",
        task_id=result.task_id,
        cleared_keys=result.cleared_keys,
    )
