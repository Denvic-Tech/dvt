from __future__ import annotations

from collections.abc import Iterable

from ...domain.entities import DataIndexEntry
from ...domain.keys import IndexKeyBase
from ..providers import PipelineCacheProvider


class PutDataEntryUseCase:
    def __init__(self, provider: PipelineCacheProvider) -> None:
        self.provider = provider

    async def execute(
        self,
        *,
        cache_key: str,
        value: object,
        ttl: int | None = None,
        index_entries: Iterable[tuple[IndexKeyBase, DataIndexEntry]] = (),
    ) -> None:
        resolved_ttl = self.provider.resolve_ttl(ttl)
        await self.provider.data_blob_store.put(
            key=cache_key,
            payload=self.provider.encode_data(value),
            ttl=resolved_ttl,
        )
        for index_key, entry in index_entries:
            await self.provider.data_index_store.put(index_key=index_key, value=entry, ttl=resolved_ttl)
