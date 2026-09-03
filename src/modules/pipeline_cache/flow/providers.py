from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..domain.entities import DataIndexEntry, MetadataCacheEntry
from ..domain.fingerprints import (
    create_dask_partition_fingerprint,
    create_node_inputs_fingerprint,
    create_node_output_fingerprint,
)
from ..domain.gateways import CacheCodec, MetadataRefreshGateway
from ..domain.keys import CommonOutputKey, DDFMetaKey, JSONKey, MetaKey, PDFKey
from ..domain.policies import resolve_ttl
from ..domain.repositories import BlobStore, IndexStore
from ..domain.value_objects import PipelineCacheSettings

if TYPE_CHECKING:
    from .facade import PipelineCacheFacade


class PipelineCacheProvider:
    def __init__(
        self,
        *,
        settings: PipelineCacheSettings,
        data_blob_store: BlobStore,
        data_index_store: IndexStore[Any, DataIndexEntry],
        metadata_blob_store: BlobStore,
        metadata_index_store: IndexStore[Any, str],
        data_codec: CacheCodec[Any],
        metadata_codec: CacheCodec[MetadataCacheEntry],
        metadata_refresh_gateway: MetadataRefreshGateway | None = None,
    ) -> None:
        self.settings = settings
        self.data_blob_store = data_blob_store
        self.data_index_store = data_index_store
        self.metadata_blob_store = metadata_blob_store
        self.metadata_index_store = metadata_index_store
        self.data_codec = data_codec
        self.metadata_codec = metadata_codec
        self.metadata_refresh_gateway = metadata_refresh_gateway

    def create_facade(self) -> "PipelineCacheFacade":
        from .facade import PipelineCacheFacade

        return PipelineCacheFacade(self)

    def resolve_ttl(self, ttl_lifetime: int | None) -> int:
        return resolve_ttl(ttl_lifetime, self.settings.default_ttl)

    def encode_data(self, value: Any) -> bytes:
        return self.data_codec.dump(value)

    def decode_data(self, payload: bytes) -> Any:
        return self.data_codec.load(payload)

    def encode_metadata(self, entry: MetadataCacheEntry) -> bytes:
        return self.metadata_codec.dump(entry)

    def decode_metadata(self, payload: bytes) -> MetadataCacheEntry:
        return self.metadata_codec.load(payload)

    def create_node_inputs_fingerprint(
        self,
        node_class: type[Any],
        parent_hashes: dict[str, str] | None = None,
        constant_inputs: dict[str, Any] | None = None,
    ) -> str:
        return create_node_inputs_fingerprint(
            node_class=node_class,
            parent_hashes=parent_hashes,
            constant_inputs=constant_inputs,
        )

    def create_node_output_fingerprint(
        self, project_id: str, node_id: str, output_name: str
    ) -> str:
        return create_node_output_fingerprint(
            project_id=project_id, node_id=node_id, output_name=output_name
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
        return create_dask_partition_fingerprint(
            pdf=pdf,
            expr_name=expr_name,
            node_name=node_name,
            part_no=part_no,
            npartitions=npartitions,
        )

    def build_data_index_keys(
        self, project_id: str, node_id: str | None = None
    ) -> list[CommonOutputKey]:
        return [
            CommonOutputKey(project_id=project_id, node_id=node_id),
            JSONKey(project_id=project_id, node_id=node_id),
            PDFKey(project_id=project_id, node_id=node_id),
            DDFMetaKey(project_id=project_id, node_id=node_id),
        ]

    def build_metadata_index_key(
        self,
        project_id: str,
        node_id: str | None = None,
        meta_key_id: str | None = None,
    ) -> MetaKey:
        return MetaKey(project_id=project_id, node_id=node_id, meta_key_id=meta_key_id)
