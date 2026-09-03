from __future__ import annotations

from typing import Any

import pandas as pd

from ...domain.dataframe_cache import (
    DATAFRAME_CACHE_FORMAT_VERSION,
    ActiveDataFrameGeneration,
    CacheGenerationState,
    DataFrameCacheManifest,
    dataframe_active_key,
    dataframe_manifest_key,
)
from ...domain.entities import GetDataFrameEntryResult
from ..exceptions import DataFrameMetadataNotFoundError, DataFramePartitionNotFoundError
from ..providers import PipelineCacheProvider


class GetDataFrameEntryUseCase:
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
    ) -> GetDataFrameEntryResult:
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

        manifest_payload = await self.provider.data_blob_store.get(
            dataframe_manifest_key(
                project_id=project_id,
                node_id=node_id,
                output_name=output_name,
                generation_id=active.generation_id,
            )
        )
        if manifest_payload is None:
            raise DataFrameMetadataNotFoundError("DataFrame cache manifest not found")
        manifest = self.provider.decode_data(manifest_payload)
        if (
            not isinstance(manifest, DataFrameCacheManifest)
            or manifest.format_version != DATAFRAME_CACHE_FORMAT_VERSION
            or manifest.state != CacheGenerationState.READY
            or manifest.project_id != project_id
            or manifest.node_id != node_id
            or manifest.output_name != output_name
            or manifest.generation_id != active.generation_id
            or len(manifest.partitions) != manifest.npartitions
        ):
            raise DataFrameMetadataNotFoundError("DataFrame cache manifest is incompatible or incomplete")

        partition_keys = tuple(entry.cache_key for entry in manifest.partitions)
        if not await self.provider.data_blob_store.has_many(partition_keys):
            raise DataFramePartitionNotFoundError(
                "DataFrame cache generation has one or more missing partitions"
            )

        total_rows = sum(manifest.rows_per_partition)
        total_partitions = manifest.npartitions
        remaining_offset = max(0, int(offset))
        remaining_limit = max(0, int(limit))
        cached_df = manifest.meta.copy()

        for entry in manifest.partitions:
            if remaining_limit <= 0:
                break
            if remaining_offset >= entry.rows:
                remaining_offset -= entry.rows
                continue

            part_payload = await self.provider.data_blob_store.get(entry.cache_key)
            if part_payload is None:
                raise DataFramePartitionNotFoundError(
                    f"DataFrame cache partition {entry.part_no} is missing from a READY generation"
                )

            part_df = self.provider.decode_data(part_payload)
            if not isinstance(part_df, pd.DataFrame):
                part_df = self._coerce_to_pandas(part_df)

            sliced = part_df.iloc[remaining_offset:] if remaining_offset else part_df
            remaining_offset = 0
            if remaining_limit < len(sliced):
                sliced = sliced.iloc[:remaining_limit]
            remaining_limit -= len(sliced)
            cached_df = pd.concat([cached_df, sliced])

        return GetDataFrameEntryResult(
            dataframe=cached_df,
            total_rows=total_rows,
            total_partitions=total_partitions,
        )

    @staticmethod
    def _coerce_to_pandas(value: Any) -> pd.DataFrame:
        if hasattr(value, "to_pandas"):
            return value.to_pandas()
        return pd.DataFrame(value)
