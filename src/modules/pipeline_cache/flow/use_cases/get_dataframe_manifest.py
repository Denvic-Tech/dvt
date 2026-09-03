from __future__ import annotations

from ...domain.dataframe_cache import (
    DATAFRAME_CACHE_FORMAT_VERSION,
    ActiveDataFrameGeneration,
    CacheGenerationState,
    DataFrameCacheManifest,
    dataframe_active_key,
    dataframe_manifest_key,
)
from ..exceptions import DataFrameMetadataNotFoundError, DataFramePartitionNotFoundError
from ..providers import PipelineCacheProvider


class GetDataFrameManifestUseCase:
    def __init__(self, provider: PipelineCacheProvider) -> None:
        self.provider = provider

    async def execute(
        self,
        *,
        project_id: str,
        node_id: str,
        output_name: str = "output",
    ) -> DataFrameCacheManifest:
        active_payload = await self.provider.data_blob_store.get(
            dataframe_active_key(project_id=project_id, node_id=node_id)
        )
        if active_payload is None:
            raise DataFrameMetadataNotFoundError("Active DataFrame cache generation not found")
        active = self.provider.decode_data(active_payload)
        if (
            not isinstance(active, ActiveDataFrameGeneration)
            or active.format_version != DATAFRAME_CACHE_FORMAT_VERSION
        ):
            raise DataFrameMetadataNotFoundError("Active DataFrame cache generation is incompatible")

        payload = await self.provider.data_blob_store.get(
            dataframe_manifest_key(
                project_id=project_id,
                node_id=node_id,
                output_name=output_name,
                generation_id=active.generation_id,
            )
        )
        if payload is None:
            raise DataFrameMetadataNotFoundError("DataFrame cache manifest not found")
        manifest = self.provider.decode_data(payload)
        if (
            not isinstance(manifest, DataFrameCacheManifest)
            or manifest.format_version != DATAFRAME_CACHE_FORMAT_VERSION
            or manifest.state != CacheGenerationState.READY
            or manifest.project_id != project_id
            or manifest.node_id != node_id
            or manifest.output_name != output_name
            or manifest.generation_id != active.generation_id
            or manifest.npartitions <= 0
            or len(manifest.partitions) != manifest.npartitions
            or len(manifest.rows_per_partition) != manifest.npartitions
            or tuple(part.part_no for part in manifest.partitions) != tuple(range(manifest.npartitions))
        ):
            raise DataFrameMetadataNotFoundError("DataFrame cache manifest is incompatible or incomplete")

        if not await self.provider.data_blob_store.has_many(
            tuple(part.cache_key for part in manifest.partitions)
        ):
            raise DataFramePartitionNotFoundError(
                "DataFrame cache generation has one or more missing partitions"
            )
        return manifest
