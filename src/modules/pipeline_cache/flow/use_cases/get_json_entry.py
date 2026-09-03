from __future__ import annotations

from ...domain.entities import GetJsonEntryResult
from ...domain.keys import JSONKey
from ..exceptions import JSONDataNotFoundError
from ..providers import PipelineCacheProvider


class GetJsonEntryUseCase:
    def __init__(self, provider: PipelineCacheProvider) -> None:
        self.provider = provider

    async def execute(
        self,
        *,
        project_id: str,
        node_id: str,
        output_name: str = "output",
        offset: int = 0,
        limit: int = 1000,
    ) -> GetJsonEntryResult:
        index_key = JSONKey(project_id=project_id, node_id=node_id, output_name=output_name)
        index_entries = await self.provider.data_index_store.query(index_key)
        entry = next(iter(index_entries), None)
        if entry is None:
            raise JSONDataNotFoundError("JSON not found in index")

        payload = await self.provider.data_blob_store.get(entry.cache_key)
        if payload is None:
            raise JSONDataNotFoundError("JSON not found in cache")

        cached = self.provider.decode_data(payload)
        if isinstance(cached, list):
            off = max(0, int(offset))
            lim = max(0, int(limit))
            data = cached[off: off + lim] if lim else []
            return GetJsonEntryResult(data=data, total_items=len(cached))

        return GetJsonEntryResult(data=cached, total_items=None)
