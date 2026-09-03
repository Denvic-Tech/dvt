from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from ..domain.entities import (
    ClearCacheResult,
    DataIndexEntry,
    GetDataFrameEntryResult,
    GetJsonEntryResult,
    RestoreMetadataEntryResult,
)
from ..domain.keys import IndexKeyBase, MetaKey
from .providers import PipelineCacheProvider
from .use_cases import (
    ClearDataCacheUseCase,
    ClearMetadataCacheUseCase,
    ClearProjectCacheUseCase,
    GetDataFrameEntryUseCase,
    GetDataFrameManifestUseCase,
    GetJsonEntryUseCase,
    PutDataEntryUseCase,
    PutMetadataEntryUseCase,
    RestoreMetadataEntryUseCase,
)


class PipelineCacheFacade:
    def __init__(self, provider: PipelineCacheProvider) -> None:
        self.provider = provider
        self._clear_data_cache = ClearDataCacheUseCase(provider)
        self._clear_metadata_cache = ClearMetadataCacheUseCase(provider)
        self._clear_project_cache = ClearProjectCacheUseCase(provider)
        self._get_dataframe_entry = GetDataFrameEntryUseCase(provider)
        self._get_dataframe_manifest = GetDataFrameManifestUseCase(provider)
        self._get_json_entry = GetJsonEntryUseCase(provider)
        self._put_data_entry = PutDataEntryUseCase(provider)
        self._put_metadata_entry = PutMetadataEntryUseCase(provider)
        self._restore_metadata_entry = RestoreMetadataEntryUseCase(provider)

    def resolve_ttl(self, ttl_lifetime: int | None) -> int:
        return self.provider.resolve_ttl(ttl_lifetime)

    def create_node_inputs_fingerprint(
        self,
        node_class: type[Any],
        parent_hashes: dict[str, str] | None = None,
        constant_inputs: dict[str, Any] | None = None,
    ) -> str:
        return self.provider.create_node_inputs_fingerprint(
            node_class=node_class,
            parent_hashes=parent_hashes,
            constant_inputs=constant_inputs,
        )

    def create_node_output_fingerprint(
        self,
        project_id: str,
        node_id: str,
        output_name: str,
    ) -> str:
        return self.provider.create_node_output_fingerprint(
            project_id=project_id,
            node_id=node_id,
            output_name=output_name,
        )

    def create_dask_partition_fingerprint(
        self,
        pdf: Any,
        *,
        expr_name: str,
        node_name: str,
        part_no: int,
        npartitions: int,
    ) -> str:
        return self.provider.create_dask_partition_fingerprint(
            pdf=pdf,
            expr_name=expr_name,
            node_name=node_name,
            part_no=part_no,
            npartitions=npartitions,
        )

    def build_data_index_keys(
        self,
        project_id: str,
        node_id: str | None = None,
    ) -> list[IndexKeyBase]:
        return self.provider.build_data_index_keys(project_id, node_id)

    def build_metadata_index_key(
        self,
        project_id: str,
        node_id: str | None = None,
        meta_key_id: str | None = None,
    ) -> MetaKey:
        return self.provider.build_metadata_index_key(
            project_id=project_id,
            node_id=node_id,
            meta_key_id=meta_key_id,
        )

    async def put_data_entry(
        self,
        *,
        cache_key: str,
        value: object,
        ttl: int | None = None,
        index_entries: Iterable[tuple[IndexKeyBase, DataIndexEntry]] = (),
    ) -> None:
        await self._put_data_entry.execute(
            cache_key=cache_key,
            value=value,
            ttl=ttl,
            index_entries=index_entries,
        )

    async def put_metadata_entry(
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
        return await self._put_metadata_entry.execute(
            project_id=project_id,
            node_id=node_id,
            cache_key=cache_key,
            outputs=outputs,
            metadata=metadata,
            ttl=ttl,
            meta_key_id=meta_key_id,
        )

    async def get_dataframe_entry(
        self,
        *,
        project_id: str,
        node_id: str,
        output_name: str = "output",
        offset: int = 0,
        limit: int = 1000,
    ) -> GetDataFrameEntryResult:
        return await self._get_dataframe_entry.execute(
            project_id=project_id,
            node_id=node_id,
            output_name=output_name,
            offset=offset,
            limit=limit,
        )

    async def get_dataframe_manifest(
        self,
        *,
        project_id: str,
        node_id: str,
        output_name: str = "output",
    ):
        return await self._get_dataframe_manifest.execute(
            project_id=project_id,
            node_id=node_id,
            output_name=output_name,
        )

    async def get_json_entry(
        self,
        *,
        project_id: str,
        node_id: str,
        output_name: str = "output",
        offset: int = 0,
        limit: int = 1000,
    ) -> GetJsonEntryResult:
        return await self._get_json_entry.execute(
            project_id=project_id,
            node_id=node_id,
            output_name=output_name,
            offset=offset,
            limit=limit,
        )

    async def restore_metadata_entry(
        self,
        *,
        meta_cache_key: str,
        expected_output_names: Iterable[str],
    ) -> RestoreMetadataEntryResult:
        return await self._restore_metadata_entry.execute(
            meta_cache_key=meta_cache_key,
            expected_output_names=expected_output_names,
        )

    async def clear_data_cache(
        self,
        *,
        project_id: str,
        node_ids: list[str] | None = None,
    ) -> ClearCacheResult:
        return await self._clear_data_cache.execute(
            project_id=project_id,
            node_ids=node_ids,
        )

    async def clear_metadata_cache(
        self,
        *,
        project_id: str,
        node_ids: list[str] | None = None,
        send_metadata_task: bool = True,
    ) -> ClearCacheResult:
        return await self._clear_metadata_cache.execute(
            project_id=project_id,
            node_ids=node_ids,
            send_metadata_task=send_metadata_task,
        )

    async def clear_project_cache(
        self,
        *,
        project_id: str,
        node_ids: list[str] | None = None,
        send_metadata_task: bool = True,
    ) -> ClearCacheResult:
        return await self._clear_project_cache.execute(
            project_id=project_id,
            node_ids=node_ids,
            send_metadata_task=send_metadata_task,
        )
