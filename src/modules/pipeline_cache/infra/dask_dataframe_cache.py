from __future__ import annotations

import logging
import threading
from concurrent.futures import Future as ConcurrentFuture
from typing import Any

import dask.dataframe as dd
import pandas as pd
from dask import delayed

logger = logging.getLogger(__name__)

from ..domain.dataframe_cache import (
    DataFrameCacheManifest,
    DataFrameCachePolicy,
    DataFramePartitionDescriptor,
)
from ..domain.gateways import DataFrameExecutionCacheGateway


def _build_restore_batches(
    manifest: DataFrameCacheManifest,
    policy: DataFrameCachePolicy,
) -> tuple[tuple[DataFramePartitionDescriptor, ...], ...]:
    """Group adjacent partitions without exceeding count/serialized-byte limits."""
    batches: list[tuple[DataFramePartitionDescriptor, ...]] = []
    current: list[DataFramePartitionDescriptor] = []
    current_bytes = 0

    for descriptor in manifest.partitions:
        exceeds_count = len(current) >= policy.max_restore_batch_partitions
        exceeds_bytes = (
            bool(current)
            and current_bytes + descriptor.payload_bytes > policy.max_restore_batch_bytes
        )
        if exceeds_count or exceeds_bytes:
            batches.append(tuple(current))
            current = []
            current_bytes = 0

        current.append(descriptor)
        current_bytes += descriptor.payload_bytes

    if current:
        batches.append(tuple(current))
    return tuple(batches)


def _load_cached_partition_batch(
    cache: DataFrameExecutionCacheGateway,
    cache_keys: tuple[str, ...],
) -> tuple[pd.DataFrame, ...]:
    from src.runtime.async_runtime import async_worker

    partitions = async_worker.run(cache.load_partitions(cache_keys))
    if len(partitions) != len(cache_keys):
        raise RuntimeError("Partition batch loader returned wrong item count")
    result: list[pd.DataFrame] = []
    for cache_key, partition in zip(cache_keys, partitions):
        if not isinstance(partition, pd.DataFrame):
            raise TypeError(f"Cached dataframe partition {cache_key!r} is not pandas.DataFrame")
        result.append(partition)
    return tuple(result)


def _select_cached_partition(
    partitions: tuple[pd.DataFrame, ...],
    index: int,
) -> pd.DataFrame:
    return partitions[index]


def build_lazy_dataframe(
    cache: DataFrameExecutionCacheGateway,
    manifest: DataFrameCacheManifest,
    *,
    policy: DataFrameCachePolicy | None = None,
) -> dd.DataFrame:
    """Build a lazy graph with bounded static batches for cached partition I/O."""
    policy = policy or DataFrameCachePolicy()
    delayed_partitions = []
    for batch in _build_restore_batches(manifest, policy):
        cache_keys = tuple(descriptor.cache_key for descriptor in batch)
        loaded_batch = delayed(_load_cached_partition_batch, pure=False)(cache, cache_keys)
        delayed_partitions.extend(
            delayed(_select_cached_partition, pure=False)(loaded_batch, index)
            for index in range(len(batch))
        )
    kwargs: dict[str, Any] = {
        "meta": manifest.meta,
        "verify_meta": True,
    }
    if manifest.known_divisions and manifest.divisions is not None:
        kwargs["divisions"] = manifest.divisions
    return dd.from_delayed(delayed_partitions, **kwargs)


class DaskPartitionCacheWriter:
    """Encode in the callback thread, then upload immutable bytes with bounded pressure."""

    def __init__(
        self,
        *,
        cache: DataFrameExecutionCacheGateway,
        project_id: str,
        node_id: str,
        output_name: str,
        generation_id: str,
        npartitions: int,
        policy: DataFrameCachePolicy,
    ) -> None:
        self.cache = cache
        self.project_id = project_id
        self.node_id = node_id
        self.output_name = output_name
        self.generation_id = generation_id
        self.npartitions = npartitions
        self.policy = policy
        self._condition = threading.Condition()
        self._pending: dict[ConcurrentFuture, int] = {}
        self._pending_bytes = 0
        self._descriptors: dict[int, DataFramePartitionDescriptor] = {}
        self._first_error: BaseException | None = None
        self._committed = False

    @property
    def pending_count(self) -> int:
        with self._condition:
            return len(self._pending)

    @property
    def pending_bytes(self) -> int:
        with self._condition:
            return self._pending_bytes

    def _record_error(self, exc: BaseException) -> None:
        with self._condition:
            if self._first_error is None:
                self._first_error = exc
            self._condition.notify_all()

    def _acquire_capacity(self, payload_bytes: int) -> None:
        with self._condition:
            while self._pending and (
                len(self._pending) >= self.policy.max_pending_partitions
                or self._pending_bytes + payload_bytes > self.policy.max_pending_bytes
            ):
                self._condition.wait()
            self._pending_bytes += payload_bytes

    def _done(self, future: ConcurrentFuture) -> None:
        descriptor: DataFramePartitionDescriptor | None = None
        error: BaseException | None = None
        try:
            descriptor = future.result()
        except BaseException as exc:  # noqa: BLE001 - cache is fail-open by policy
            error = exc
        with self._condition:
            size = self._pending.pop(future, 0)
            self._pending_bytes = max(0, self._pending_bytes - size)
            if descriptor is not None:
                self._descriptors[descriptor.part_no] = descriptor
            if error is not None and self._first_error is None:
                self._first_error = error
            self._condition.notify_all()

    def submit_partition(self, partition: pd.DataFrame, *, part_no: int) -> None:
        from src.runtime.async_runtime import async_worker

        if self._committed:
            return
        try:
            # Critical lifetime boundary: no pandas object survives past this call.
            payload = self.cache.encode_partition(partition)
        except BaseException as exc:  # noqa: BLE001
            self._record_error(exc)
            return

        payload_bytes = len(payload)
        self._acquire_capacity(payload_bytes)
        try:
            future = async_worker.submit(
                self.cache.put_encoded_partition(
                    project_id=self.project_id,
                    node_id=self.node_id,
                    output_name=self.output_name,
                    generation_id=self.generation_id,
                    part_no=part_no,
                    rows=len(partition),
                    payload=payload,
                )
            )
        except BaseException as exc:  # noqa: BLE001
            with self._condition:
                self._pending_bytes = max(0, self._pending_bytes - payload_bytes)
                self._condition.notify_all()
            self._record_error(exc)
            return
        with self._condition:
            self._pending[future] = payload_bytes
        future.add_done_callback(self._done)

    def finish(self) -> bool:
        from src.runtime.async_runtime import async_worker

        if self._committed:
            return True
        while True:
            with self._condition:
                if not self._pending:
                    break
                self._condition.wait()

        with self._condition:
            error = self._first_error
            descriptors = tuple(self._descriptors.values())

        if error is not None or len(descriptors) != self.npartitions:
            try:
                async_worker.run(
                    self.cache.abort_output_generation(
                        project_id=self.project_id,
                        node_id=self.node_id,
                        output_name=self.output_name,
                        generation_id=self.generation_id,
                    )
                )
            except Exception:
                pass
            message = (
                f"Dataframe cache generation aborted for {self.node_id}.{self.output_name}: "
                f"stored={len(descriptors)}/{self.npartitions}"
            )
            if error is not None:
                logger.error("%s: %s", message, error)
            else:
                logger.error("%s", message)
            if self.policy.strict:
                raise RuntimeError(message) from error
            return False

        try:
            async_worker.run(
                self.cache.commit_output_generation(
                    project_id=self.project_id,
                    node_id=self.node_id,
                    output_name=self.output_name,
                    generation_id=self.generation_id,
                    partitions=descriptors,
                )
            )
        except BaseException as exc:  # noqa: BLE001
            try:
                async_worker.run(
                    self.cache.abort_output_generation(
                        project_id=self.project_id,
                        node_id=self.node_id,
                        output_name=self.output_name,
                        generation_id=self.generation_id,
                    )
                )
            except Exception:
                pass
            logger.exception(
                "Failed to commit dataframe cache generation for %s.%s",
                self.node_id,
                self.output_name,
            )
            if self.policy.strict:
                raise RuntimeError("Failed to commit dataframe cache generation") from exc
            return False

        self._committed = True
        return True

    def abort(self) -> None:
        from src.runtime.async_runtime import async_worker

        if self._committed:
            return
        try:
            async_worker.run(
                self.cache.abort_output_generation(
                    project_id=self.project_id,
                    node_id=self.node_id,
                    output_name=self.output_name,
                    generation_id=self.generation_id,
                )
            )
        except Exception:
            logger.exception(
                "Failed to mark dataframe cache generation aborted for %s.%s",
                self.node_id,
                self.output_name,
            )
