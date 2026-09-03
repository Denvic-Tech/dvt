from __future__ import annotations

from uuid import uuid4

from ...domain.entities import MetadataCacheEntry
from ..providers import PipelineCacheProvider


class PutMetadataEntryUseCase:
    def __init__(self, provider: PipelineCacheProvider) -> None:
        self.provider = provider

    async def execute(
        self,
        *,
        project_id: str,
        node_id: str,
        cache_key: str,
        outputs: dict[str, object],
        metadata: dict[str, object] | None,
        ttl: int | None = None,
        meta_key_id: str | None = None,
    ) -> str:
        resolved_ttl = self.provider.resolve_ttl(ttl)
        entry = MetadataCacheEntry.create(
            outputs=outputs,
            metadata=metadata,
        )
        await self.provider.metadata_blob_store.put(
            key=cache_key,
            payload=self.provider.encode_metadata(entry),
            ttl=resolved_ttl,
        )

        resolved_meta_key_id = meta_key_id or str(uuid4())
        index_key = self.provider.build_metadata_index_key(
            project_id=project_id,
            node_id=node_id,
            meta_key_id=resolved_meta_key_id,
        )
        await self.provider.metadata_index_store.put(index_key=index_key, value=cache_key, ttl=resolved_ttl)
        return resolved_meta_key_id
