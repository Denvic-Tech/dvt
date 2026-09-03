from __future__ import annotations

import asyncio
from time import time
from typing import Any
from uuid import uuid4

from ..domain.dataframe_cache import (
    DATAFRAME_CACHE_FORMAT_VERSION,
    ActiveDataFrameGeneration,
    CacheGenerationState,
    DataFrameCacheManifest,
    DataFrameCachePolicy,
    DataFrameExecutionOrder,
    DataFrameExecutionSnapshot,
    DataFramePartitionDescriptor,
    DataFrameRestorePlan,
    dataframe_active_key,
    dataframe_manifest_key,
    dataframe_partition_key,
    dataframe_snapshot_key,
)
from ..domain.fingerprints import create_dataframe_schema_fingerprint
from ..domain.repositories import EncodedObjectStore


class DataFrameCacheMiss(Exception):
    """The execution cache cannot safely satisfy a restore request."""


class DataFrameCacheCorruptionError(RuntimeError):
    """A committed cache generation is incomplete or internally inconsistent."""


class DataFrameExecutionCache:
    """Application service owning dataframe cache generation invariants."""

    def __init__(
        self,
        *,
        data_store: EncodedObjectStore[Any],
        ttl_lifetime: int | None = None,
        policy: DataFrameCachePolicy | None = None,
    ) -> None:
        self.data_store = data_store
        self.ttl_lifetime = ttl_lifetime
        self.policy = policy or DataFrameCachePolicy()

    @staticmethod
    def new_generation_id() -> str:
        return uuid4().hex

    async def begin_output_generation(
        self,
        *,
        project_id: str,
        node_id: str,
        output_name: str,
        generation_id: str,
        node_runtime_fingerprint: str,
        meta: Any,
        npartitions: int,
        known_divisions: bool,
        divisions: tuple[Any, ...] | None,
    ) -> DataFrameCacheManifest:
        if npartitions <= 0:
            raise ValueError("DataFrame cache requires at least one partition")
        manifest = DataFrameCacheManifest.writing(
            project_id=project_id,
            node_id=node_id,
            output_name=output_name,
            generation_id=generation_id,
            node_runtime_fingerprint=node_runtime_fingerprint,
            schema_fingerprint=create_dataframe_schema_fingerprint(meta),
            meta=meta,
            npartitions=npartitions,
            known_divisions=known_divisions,
            divisions=tuple(divisions) if known_divisions and divisions is not None else None,
        )
        await self.data_store.put(
            dataframe_manifest_key(
                project_id=project_id,
                node_id=node_id,
                output_name=output_name,
                generation_id=generation_id,
            ),
            manifest,
            ttl_lifetime=self.ttl_lifetime,
        )
        return manifest

    def encode_partition(self, partition: Any) -> bytes:
        store = self.data_store
        encode = getattr(store, "encode", None)
        if encode is None:
            raise TypeError("Configured dataframe object store does not support detached encoding")
        payload = encode(partition)
        if not isinstance(payload, bytes):
            raise TypeError("Encoded dataframe partition must be bytes")
        return payload

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
    ) -> DataFramePartitionDescriptor:
        key = dataframe_partition_key(
            project_id=project_id,
            node_id=node_id,
            output_name=output_name,
            generation_id=generation_id,
            part_no=part_no,
        )
        put_encoded = getattr(self.data_store, "put_encoded", None)
        if put_encoded is None:
            raise TypeError("Configured dataframe object store does not support detached encoded writes")
        await put_encoded(key, payload, self.ttl_lifetime)
        return DataFramePartitionDescriptor(
            part_no=part_no,
            cache_key=key,
            rows=rows,
            payload_bytes=len(payload),
        )

    async def commit_output_generation(
        self,
        *,
        project_id: str,
        node_id: str,
        output_name: str,
        generation_id: str,
        partitions: tuple[DataFramePartitionDescriptor, ...],
    ) -> DataFrameCacheManifest:
        key = dataframe_manifest_key(
            project_id=project_id,
            node_id=node_id,
            output_name=output_name,
            generation_id=generation_id,
        )
        manifest = await self.data_store.get(key)
        if not isinstance(manifest, DataFrameCacheManifest):
            raise DataFrameCacheCorruptionError("WRITING dataframe cache manifest disappeared before commit")
        if manifest.state != CacheGenerationState.WRITING:
            raise DataFrameCacheCorruptionError(
                f"Cannot commit dataframe cache generation in state={manifest.state}"
            )
        ready = manifest.ready(partitions)
        await self.data_store.put(key, ready, ttl_lifetime=self.ttl_lifetime)
        await self._try_activate_node_generation(
            project_id=project_id,
            node_id=node_id,
            generation_id=generation_id,
        )
        return ready

    async def abort_output_generation(
        self,
        *,
        project_id: str,
        node_id: str,
        output_name: str,
        generation_id: str,
    ) -> None:
        key = dataframe_manifest_key(
            project_id=project_id,
            node_id=node_id,
            output_name=output_name,
            generation_id=generation_id,
        )
        try:
            manifest = await self.data_store.get(key)
            if isinstance(manifest, DataFrameCacheManifest):
                await self.data_store.put(key, manifest.aborted(), ttl_lifetime=self.ttl_lifetime)
        except Exception:
            # Best-effort state marking: cache failure must not hide the original ETL result.
            return

    async def stage_execution_snapshot(
        self,
        *,
        project_id: str,
        node_id: str,
        generation_id: str,
        node_name: str,
        node_runtime_fingerprint: str,
        output_names: tuple[str, ...],
        dataframe_output_names: tuple[str, ...],
        non_dataframe_outputs: dict[str, Any],
        metadata: dict[str, Any],
        execution_order: DataFrameExecutionOrder | None = None,
    ) -> DataFrameExecutionSnapshot:
        snapshot = DataFrameExecutionSnapshot(
            format_version=DATAFRAME_CACHE_FORMAT_VERSION,
            project_id=project_id,
            node_id=node_id,
            generation_id=generation_id,
            node_name=node_name,
            node_runtime_fingerprint=node_runtime_fingerprint,
            output_names=output_names,
            dataframe_output_names=dataframe_output_names,
            non_dataframe_outputs=dict(non_dataframe_outputs),
            metadata=dict(metadata),
            created_at=time(),
            execution_order=execution_order,
        )
        await self.data_store.put(
            dataframe_snapshot_key(
                project_id=project_id,
                node_id=node_id,
                generation_id=generation_id,
            ),
            snapshot,
            ttl_lifetime=self.ttl_lifetime,
        )
        await self._try_activate_node_generation(
            project_id=project_id,
            node_id=node_id,
            generation_id=generation_id,
        )
        return snapshot

    async def _try_activate_node_generation(
        self,
        *,
        project_id: str,
        node_id: str,
        generation_id: str,
    ) -> bool:
        snapshot = await self.data_store.get(
            dataframe_snapshot_key(
                project_id=project_id,
                node_id=node_id,
                generation_id=generation_id,
            )
        )
        if not isinstance(snapshot, DataFrameExecutionSnapshot):
            return False
        if snapshot.format_version != DATAFRAME_CACHE_FORMAT_VERSION:
            return False
        if snapshot.execution_order is None:
            return False

        for output_name in snapshot.dataframe_output_names:
            manifest = await self.data_store.get(
                dataframe_manifest_key(
                    project_id=project_id,
                    node_id=node_id,
                    output_name=output_name,
                    generation_id=generation_id,
                )
            )
            if not isinstance(manifest, DataFrameCacheManifest):
                return False
            if manifest.state != CacheGenerationState.READY:
                return False
            if manifest.format_version != DATAFRAME_CACHE_FORMAT_VERSION:
                return False
            if manifest.node_runtime_fingerprint != snapshot.node_runtime_fingerprint:
                return False

        return await self._activate_if_newer(
            project_id=project_id,
            node_id=node_id,
            generation_id=generation_id,
            execution_order=snapshot.execution_order,
        )

    async def _activate_if_newer(
        self,
        *,
        project_id: str,
        node_id: str,
        generation_id: str,
        execution_order: DataFrameExecutionOrder,
    ) -> bool:
        key = dataframe_active_key(project_id=project_id, node_id=node_id)
        candidate = ActiveDataFrameGeneration(
            format_version=DATAFRAME_CACHE_FORMAT_VERSION,
            generation_id=generation_id,
            activated_at=time(),
            execution_order=execution_order,
        )
        candidate_payload = self.data_store.encode(candidate)

        while True:
            current_payload = await self.data_store.get_encoded(key)
            current: ActiveDataFrameGeneration | None = None
            if current_payload is not None:
                decoded = self.data_store.decode(current_payload)
                if isinstance(decoded, ActiveDataFrameGeneration):
                    current = decoded

            if current is not None and current.format_version == DATAFRAME_CACHE_FORMAT_VERSION:
                if current.execution_order is not None:
                    if current.execution_order > execution_order:
                        return False
                    if current.execution_order == execution_order:
                        return current.generation_id == generation_id

            swapped = await self.data_store.compare_and_set_encoded(
                key,
                expected=current_payload,
                payload=candidate_payload,
                ttl_lifetime=self.ttl_lifetime,
            )
            if swapped:
                return True

    async def get_restore_plan(
        self,
        *,
        project_id: str,
        node_id: str,
        node_name: str,
        node_runtime_fingerprint: str | None,
        expected_output_names: tuple[str, ...],
    ) -> DataFrameRestorePlan | None:
        active = await self.data_store.get(dataframe_active_key(project_id=project_id, node_id=node_id))
        if not isinstance(active, ActiveDataFrameGeneration):
            return None
        if active.format_version != DATAFRAME_CACHE_FORMAT_VERSION:
            return None

        snapshot = await self.data_store.get(
            dataframe_snapshot_key(
                project_id=project_id,
                node_id=node_id,
                generation_id=active.generation_id,
            )
        )
        if not isinstance(snapshot, DataFrameExecutionSnapshot):
            return None
        if (
            snapshot.format_version != DATAFRAME_CACHE_FORMAT_VERSION
            or snapshot.project_id != project_id
            or snapshot.node_id != node_id
            or snapshot.generation_id != active.generation_id
            or snapshot.node_name != node_name
            or (
                node_runtime_fingerprint is not None
                and snapshot.node_runtime_fingerprint != node_runtime_fingerprint
            )
            or snapshot.output_names != expected_output_names
        ):
            return None
        if set(snapshot.non_dataframe_outputs) != (
            set(expected_output_names) - set(snapshot.dataframe_output_names)
        ):
            return None
        if any(
            output_name not in snapshot.metadata or snapshot.metadata[output_name] is None
            for output_name in snapshot.dataframe_output_names
        ):
            return None

        expected_runtime_fingerprint: str = (
            node_runtime_fingerprint or snapshot.node_runtime_fingerprint
        )
        manifests: dict[str, DataFrameCacheManifest] = {}
        for output_name in snapshot.dataframe_output_names:
            manifest = await self.data_store.get(
                dataframe_manifest_key(
                    project_id=project_id,
                    node_id=node_id,
                    output_name=output_name,
                    generation_id=active.generation_id,
                )
            )
            if not isinstance(manifest, DataFrameCacheManifest):
                return None
            if not self._manifest_is_compatible(
                manifest,
                project_id=project_id,
                node_id=node_id,
                output_name=output_name,
                generation_id=active.generation_id,
                node_runtime_fingerprint=expected_runtime_fingerprint,
            ):
                return None
            manifests[output_name] = manifest

        partition_keys = [
            descriptor.cache_key
            for manifest in manifests.values()
            for descriptor in manifest.partitions
        ]
        has_many = getattr(self.data_store, "has_many", None)
        if has_many is not None:
            if not await has_many(partition_keys):
                return None
        else:
            has_one = getattr(self.data_store, "has", None)
            if has_one is not None:
                for cache_key in partition_keys:
                    if not await has_one(cache_key):
                        return None

        return DataFrameRestorePlan(snapshot=snapshot, manifests=manifests)

    @staticmethod
    def _manifest_is_compatible(
        manifest: DataFrameCacheManifest,
        *,
        project_id: str,
        node_id: str,
        output_name: str,
        generation_id: str,
        node_runtime_fingerprint: str,
    ) -> bool:
        if (
            manifest.format_version != DATAFRAME_CACHE_FORMAT_VERSION
            or manifest.state != CacheGenerationState.READY
            or manifest.project_id != project_id
            or manifest.node_id != node_id
            or manifest.output_name != output_name
            or manifest.generation_id != generation_id
            or manifest.node_runtime_fingerprint != node_runtime_fingerprint
            or manifest.npartitions <= 0
            or len(manifest.partitions) != manifest.npartitions
            or len(manifest.rows_per_partition) != manifest.npartitions
            or tuple(part.part_no for part in manifest.partitions) != tuple(range(manifest.npartitions))
        ):
            return False
        if create_dataframe_schema_fingerprint(manifest.meta) != manifest.schema_fingerprint:
            return False
        if manifest.known_divisions:
            if manifest.divisions is None or len(manifest.divisions) != manifest.npartitions + 1:
                return False
        elif manifest.divisions is not None:
            return False
        return True

    async def load_partition(self, cache_key: str) -> Any:
        partition = await self.data_store.get(cache_key)
        if partition is None:
            raise DataFrameCacheCorruptionError(f"Cached dataframe partition is missing: {cache_key}")
        return partition

    async def load_partitions(self, cache_keys: tuple[str, ...]) -> tuple[Any, ...]:
        get_many = getattr(self.data_store, "get_many", None)
        if get_many is not None:
            partitions = await get_many(cache_keys)
        else:
            partitions = await asyncio.gather(
                *(self.data_store.get(cache_key) for cache_key in cache_keys)
            )
        if len(partitions) != len(cache_keys):
            raise DataFrameCacheCorruptionError("Cached dataframe batch returned wrong partition count")
        missing = [
            cache_key
            for cache_key, partition in zip(cache_keys, partitions)
            if partition is None
        ]
        if missing:
            raise DataFrameCacheCorruptionError(
                f"Cached dataframe partitions are missing: {missing!r}"
            )
        return tuple(partitions)
