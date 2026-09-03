from collections.abc import AsyncIterator
from typing import Annotated
from urllib.parse import quote

import orjson
import pandas as pd
from fastapi import APIRouter, Depends
from fastapi.params import Query
from starlette.responses import StreamingResponse

from core.metadata import get_df_metadata
from core.types import DataFrameData

from services.gateway.deps.caching import get_data_store, get_pipeline_cache_facade
from services.gateway.deps.project import UserProjectByPath

from src.crud import project as project_crud
from src.db.fastapi.dependencies import AsyncSessionDepends
from src.exception_registry.errors_list.gateway import project as project_exc
from src.exceptions import ProjectNotFoundException
from src.modules.pipeline_cache import ObjectStore, PipelineCacheFacade
from src.modules.pipeline_cache.domain.dataframe_cache import DataFramePartitionDescriptor
from src.modules.user.infra.fastapi.dependencies import UserAccessOnly
from src.utils.access_control import get_access_scope

r = router = APIRouter()


@r.get("/{node_id}", response_model=DataFrameData)
async def dataframe_data(
        pipeline_cache: Annotated[PipelineCacheFacade, Depends(get_pipeline_cache_facade)],
        project: UserProjectByPath,
        project_id: str,
        node_id: str,
        output_name: Annotated[str, Query()] = "output",
        offset: Annotated[int, Query()] = 0,
        limit: Annotated[int, Query()] = 1000,
):
    try:
        result = await pipeline_cache.get_dataframe_entry(
            project_id=project_id,
            node_id=node_id,
            output_name=output_name,
            offset=offset,
            limit=limit,
        )
    except Exception as exc:
        detail = str(exc)
        if "metadata" in detail.lower():
            raise project_exc.DataFrameMetaNotFound(status_code=404) from exc
        raise project_exc.DataFrameNotFound(status_code=404, detail=detail) from exc

    df_metadata = get_df_metadata(result.dataframe)
    part_data = result.dataframe.to_json(orient="split", date_format="iso", default_handler=str)
    df_values = orjson.loads(part_data).get("data", [])

    return DataFrameData(
        columns=df_metadata.columns,
        values=df_values,

        total_rows=result.total_rows,
        total_partitions=result.total_partitions,
    )


async def _stream_csv_partitions(
        partition_entries: tuple[DataFramePartitionDescriptor, ...],
        data_store: ObjectStore[pd.DataFrame],
) -> AsyncIterator[bytes]:
    """Async generator that streams DataFrame partitions as CSV chunks.

    Uses UTF-8 with BOM (utf-8-sig) for the first chunk to ensure proper
    recognition of Cyrillic and other non-ASCII characters in Excel.
    """
    header_written = False

    for entry in partition_entries:
        part_df = await data_store.get(entry.cache_key)
        if part_df is None:
            raise RuntimeError(
                f"READY DataFrame cache generation is missing partition {entry.part_no}"
            )

        if not isinstance(part_df, pd.DataFrame):
            part_df = part_df.to_pandas() if hasattr(part_df, "to_pandas") else pd.DataFrame(part_df)

        csv_chunk = part_df.to_csv(
            index=False,
            header=not header_written,
        )

        if not header_written:
            # First chunk: encode with BOM for Excel compatibility
            yield csv_chunk.encode("utf-8-sig")
        else:
            yield csv_chunk.encode("utf-8")

        header_written = True


@r.get("/{node_id}/download")
async def download_dataframe_csv(
        session: AsyncSessionDepends,
        data_store: Annotated[ObjectStore[pd.DataFrame], Depends(get_data_store)],
        pipeline_cache: Annotated[PipelineCacheFacade, Depends(get_pipeline_cache_facade)],
        user: UserAccessOnly,
        project_id: str,
        node_id: str,
        output_name: Annotated[str, Query()] = "output",
) -> StreamingResponse:
    """Download full DataFrame as CSV file via streaming."""
    # Надо так:
    access_scope = get_access_scope(user)
    project = (await project_crud.get_projects_by(
        session=session,
        organization_id=access_scope.organization_id,
        owner_user_id=access_scope.owner_user_id,
        project_id=project_id,
    )).first()

    if not project:
        raise ProjectNotFoundException(status_code=404, detail="Project not found")

    try:
        manifest = await pipeline_cache.get_dataframe_manifest(
            project_id=project_id,
            node_id=node_id,
            output_name=output_name,
        )
    except Exception as exc:
        raise project_exc.DataFrameNotFound(
            status_code=404,
            detail="DataFrame not found in cache",
        ) from exc

    filename = f"{project.name}_{node_id}_{output_name}.csv"
    filename_ascii = "dataframe.csv"  # fallback (можешь сделать свой)

    headers = {
        "Content-Disposition": (
            f'attachment; filename="{filename_ascii}"; '
            f"filename*=UTF-8''{quote(filename)}"
        )
    }

    return StreamingResponse(
        _stream_csv_partitions(manifest.partitions, data_store),
        media_type="text/csv",
        headers=headers,
    )
