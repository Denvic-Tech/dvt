from __future__ import annotations

from ..providers import PipelineCacheProvider
from ...domain.entities import ClearCacheResult
from .clear_data_cache import ClearDataCacheUseCase
from .clear_metadata_cache import ClearMetadataCacheUseCase


class ClearProjectCacheUseCase:
    def __init__(self, provider: PipelineCacheProvider) -> None:
        self._clear_data_cache = ClearDataCacheUseCase(provider)
        self._clear_metadata_cache = ClearMetadataCacheUseCase(provider)

    async def execute(
        self,
        *,
        project_id: str,
        node_ids: list[str] | None = None,
        send_metadata_task: bool = True,
    ) -> ClearCacheResult:
        data_result = await self._clear_data_cache.execute(project_id=project_id, node_ids=node_ids)
        metadata_result = await self._clear_metadata_cache.execute(
            project_id=project_id,
            node_ids=node_ids,
            send_metadata_task=send_metadata_task,
        )
        return ClearCacheResult(
            cleared_keys=[*data_result.cleared_keys, *metadata_result.cleared_keys],
            task_id=metadata_result.task_id,
        )
