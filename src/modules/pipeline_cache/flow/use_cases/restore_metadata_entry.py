from __future__ import annotations

from collections.abc import Iterable

from ...domain.entities import RestoreMetadataEntryResult
from ..providers import PipelineCacheProvider


class RestoreMetadataEntryUseCase:
    def __init__(self, provider: PipelineCacheProvider) -> None:
        self.provider = provider

    async def execute(
        self,
        *,
        meta_cache_key: str,
        expected_output_names: Iterable[str],
    ) -> RestoreMetadataEntryResult:
        payload = await self.provider.metadata_blob_store.get(meta_cache_key)
        if payload is None:
            return RestoreMetadataEntryResult(restored=False)

        normalized_entry = self.provider.decode_metadata(payload).normalized_for_outputs(expected_output_names)
        if normalized_entry is None:
            return RestoreMetadataEntryResult(restored=False)
        return RestoreMetadataEntryResult(restored=True, entry=normalized_entry)
