from typing import Annotated

from fastapi import APIRouter, Depends

from services.gateway.deps.caching import (
    get_pipeline_cache_facade,
)
from services.gateway.deps.project import UserProjectByPath

from src.exception_registry.errors_list.gateway import project as project_exc
from src.modules.pipeline_cache import PipelineCacheFacade

from .schemas import JSONData

r = router = APIRouter()


@r.get("/{node_id}", response_model=JSONData)
async def json_data(
    pipeline_cache: Annotated[PipelineCacheFacade, Depends(get_pipeline_cache_facade)],
    project: UserProjectByPath,
    project_id: str,
    node_id: str,
    output_name: str = "output",
    offset: int = 0,
    limit: int = 1000,
) -> JSONData:
    try:
        result = await pipeline_cache.get_json_entry(
            project_id=project_id,
            node_id=node_id,
            output_name=output_name,
            offset=offset,
            limit=limit,
        )
    except Exception as exc:
        raise project_exc.JSONNotFound(status_code=404, detail=str(exc)) from exc

    return JSONData(data=result.data, total_items=result.total_items)
