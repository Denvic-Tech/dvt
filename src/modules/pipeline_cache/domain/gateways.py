from __future__ import annotations

from typing import Any, Protocol, TypeVar

from .dataframe_cache import DataFramePartitionDescriptor

T = TypeVar("T")


class CacheCodec(Protocol[T]):
    def dump(self, value: T) -> bytes: ...
    def load(self, payload: bytes) -> T: ...


class MetadataRefreshGateway(Protocol):
    async def request_refresh(self, *, project_id: str, node_ids: list[str] | None = None) -> str | None: ...


class DataFrameExecutionCacheGateway(Protocol):
    """Boundary used by the Dask adapter without depending on application flow."""

    def encode_partition(self, partition: Any) -> bytes: ...

    async def put_encoded_partition(
        self,
        *,
        project_id: str,
        node_id: str,
        output_name: str,
        generation_id: str,
        part_no: int,
        rows: int,
        payload: bytes,
    ) -> DataFramePartitionDescriptor: ...

    async def commit_output_generation(
        self,
        *,
        project_id: str,
        node_id: str,
        output_name: str,
        generation_id: str,
        partitions: tuple[DataFramePartitionDescriptor, ...],
    ) -> Any: ...

    async def abort_output_generation(
        self,
        *,
        project_id: str,
        node_id: str,
        output_name: str,
        generation_id: str,
    ) -> None: ...

    async def load_partition(self, cache_key: str) -> Any: ...

    async def load_partitions(self, cache_keys: tuple[str, ...]) -> tuple[Any, ...]: ...


class LazyDataFrameFactory(Protocol):
    def build(
        self,
        *,
        partition_refs: tuple[str, ...],
        meta: Any,
        divisions: tuple[Any, ...] | None,
        partition_loader: Any,
    ) -> Any: ...
