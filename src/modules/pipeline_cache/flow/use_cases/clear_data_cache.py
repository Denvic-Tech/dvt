from __future__ import annotations

from ...domain.entities import ClearCacheResult
from ...domain.policies import dedupe_preserve_order
from ..providers import PipelineCacheProvider


class ClearDataCacheUseCase:
    def __init__(self, provider: PipelineCacheProvider) -> None:
        self.provider = provider

    async def execute(self, *, project_id: str, node_ids: list[str] | None = None) -> ClearCacheResult:
        cache_keys: list[str] = []

        # Generation-backed dataframe cache is intentionally independent from the
        # legacy partition index. Clear it by its deterministic namespace so stale
        # READY generations cannot become reachable again and orphan blobs are
        # reclaimed immediately instead of waiting for TTL.
        prefixes = (
            [f"df:{project_id}:{node_id}:" for node_id in node_ids]
            if node_ids is not None
            else [f"df:{project_id}:"]
        )
        for prefix in prefixes:
            cache_keys.extend(await self.provider.data_blob_store.keys(prefix))

        if node_ids is not None:
            for node_id in node_ids:
                for index_key in self.provider.build_data_index_keys(project_id, node_id):
                    cached_entries = await self.provider.data_index_store.query(index_key)
                    cache_keys.extend([entry.cache_key for entry in cached_entries])

                    await self.provider.data_index_store.remove(index_key)
        else:
            for index_key in self.provider.build_data_index_keys(project_id):
                cached_entries = await self.provider.data_index_store.query(index_key)
                cache_keys.extend([entry.cache_key for entry in cached_entries])
                await self.provider.data_index_store.remove(index_key)

        cache_keys = dedupe_preserve_order(cache_keys)
        if cache_keys:
            await self.provider.data_blob_store.remove(cache_keys[0], *cache_keys[1:])

        return ClearCacheResult(cleared_keys=cache_keys)
