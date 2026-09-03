from __future__ import annotations

from ..providers import PipelineCacheProvider
from ...domain.entities import ClearCacheResult


class ClearMetadataCacheUseCase:
    def __init__(self, provider: PipelineCacheProvider) -> None:
        self.provider = provider

    async def execute(
        self,
        *,
        project_id: str,
        node_ids: list[str] | None = None,
        send_metadata_task: bool = True,
    ) -> ClearCacheResult:
        cache_keys: list[str] = []

        if node_ids is not None:
            for node_id in node_ids:
                index_key = self.provider.build_metadata_index_key(project_id=project_id, node_id=node_id)
                cache_keys.extend(await self.provider.metadata_index_store.query(index_key))
                await self.provider.metadata_index_store.remove(index_key)
        else:
            index_key = self.provider.build_metadata_index_key(project_id=project_id)
            cache_keys.extend(await self.provider.metadata_index_store.query(index_key))
            await self.provider.metadata_index_store.remove(index_key)

        if cache_keys:
            await self.provider.metadata_blob_store.remove(cache_keys[0], *cache_keys[1:])

        task_id: str | None = None
        if send_metadata_task and self.provider.metadata_refresh_gateway is not None:
            task_id = await self.provider.metadata_refresh_gateway.enqueue_metadata_refresh(
                project_id=project_id,
                node_ids=node_ids,
            )

        return ClearCacheResult(cleared_keys=cache_keys, task_id=task_id)
