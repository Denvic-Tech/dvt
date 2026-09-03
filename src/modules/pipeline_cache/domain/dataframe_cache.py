from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from time import time
from typing import Any

DATAFRAME_CACHE_FORMAT_VERSION = 3


@dataclass(frozen=True, order=True, slots=True)
class DataFrameExecutionOrder:
    """Authoritative total order of pipeline executions for cache activation."""

    queued_at_us: int
    task_id: str

    @classmethod
    def from_queued_at(cls, queued_at: datetime, task_id: str) -> DataFrameExecutionOrder:
        if queued_at.tzinfo is None:
            queued_at = queued_at.replace(tzinfo=UTC)
        normalized = queued_at.astimezone(UTC)
        epoch = datetime(1970, 1, 1, tzinfo=UTC)
        delta = normalized - epoch
        queued_at_us = (
            delta.days * 86_400_000_000
            + delta.seconds * 1_000_000
            + delta.microseconds
        )
        return cls(queued_at_us=queued_at_us, task_id=task_id)


@dataclass(frozen=True, slots=True)
class DataFrameCachePolicy:
    strict: bool = False
    max_pending_partitions: int = 32
    max_pending_bytes: int = 128 * 1024 * 1024
    max_restore_batch_partitions: int = 32
    max_restore_batch_bytes: int = 2 * 1024 * 1024

    def __post_init__(self) -> None:
        if self.max_pending_partitions <= 0:
            raise ValueError("max_pending_partitions must be positive")
        if self.max_pending_bytes <= 0:
            raise ValueError("max_pending_bytes must be positive")
        if self.max_restore_batch_partitions <= 0:
            raise ValueError("max_restore_batch_partitions must be positive")
        if self.max_restore_batch_bytes <= 0:
            raise ValueError("max_restore_batch_bytes must be positive")


class CacheGenerationState(StrEnum):
    WRITING = "WRITING"
    READY = "READY"
    ABORTED = "ABORTED"
    INVALID = "INVALID"


@dataclass(frozen=True, slots=True)
class DataFramePartitionDescriptor:
    part_no: int
    cache_key: str
    rows: int
    payload_bytes: int


@dataclass(frozen=True, slots=True)
class DataFrameCacheManifest:
    format_version: int
    project_id: str
    node_id: str
    output_name: str
    generation_id: str
    node_runtime_fingerprint: str
    schema_fingerprint: str
    meta: Any
    npartitions: int
    partitions: tuple[DataFramePartitionDescriptor, ...]
    rows_per_partition: tuple[int, ...]
    known_divisions: bool
    divisions: tuple[Any, ...] | None
    created_at: float
    state: CacheGenerationState

    @classmethod
    def writing(
        cls,
        *,
        project_id: str,
        node_id: str,
        output_name: str,
        generation_id: str,
        node_runtime_fingerprint: str,
        schema_fingerprint: str,
        meta: Any,
        npartitions: int,
        known_divisions: bool,
        divisions: tuple[Any, ...] | None,
    ) -> DataFrameCacheManifest:
        return cls(
            format_version=DATAFRAME_CACHE_FORMAT_VERSION,
            project_id=project_id,
            node_id=node_id,
            output_name=output_name,
            generation_id=generation_id,
            node_runtime_fingerprint=node_runtime_fingerprint,
            schema_fingerprint=schema_fingerprint,
            meta=meta,
            npartitions=npartitions,
            partitions=(),
            rows_per_partition=(),
            known_divisions=known_divisions,
            divisions=divisions,
            created_at=time(),
            state=CacheGenerationState.WRITING,
        )

    def ready(self, partitions: tuple[DataFramePartitionDescriptor, ...]) -> DataFrameCacheManifest:
        ordered = tuple(sorted(partitions, key=lambda item: item.part_no))
        if len(ordered) != self.npartitions:
            raise ValueError(
                f"Cannot commit dataframe generation with {len(ordered)}/{self.npartitions} partitions"
            )
        if tuple(item.part_no for item in ordered) != tuple(range(self.npartitions)):
            raise ValueError("Cannot commit dataframe generation with missing/duplicate partition numbers")
        return replace(
            self,
            partitions=ordered,
            rows_per_partition=tuple(item.rows for item in ordered),
            state=CacheGenerationState.READY,
        )

    def aborted(self) -> DataFrameCacheManifest:
        return replace(self, state=CacheGenerationState.ABORTED)


@dataclass(frozen=True, slots=True)
class DataFrameExecutionSnapshot:
    format_version: int
    project_id: str
    node_id: str
    generation_id: str
    node_name: str
    node_runtime_fingerprint: str
    output_names: tuple[str, ...]
    dataframe_output_names: tuple[str, ...]
    non_dataframe_outputs: dict[str, Any]
    metadata: dict[str, Any]
    created_at: float
    execution_order: DataFrameExecutionOrder | None = None


@dataclass(frozen=True, slots=True)
class ActiveDataFrameGeneration:
    format_version: int
    generation_id: str
    activated_at: float
    execution_order: DataFrameExecutionOrder | None = None


@dataclass(frozen=True, slots=True)
class DataFrameRestorePlan:
    snapshot: DataFrameExecutionSnapshot
    manifests: dict[str, DataFrameCacheManifest]


def dataframe_partition_key(
    *, project_id: str, node_id: str, output_name: str, generation_id: str, part_no: int
) -> str:
    return f"df:{project_id}:{node_id}:{output_name}:{generation_id}:part:{part_no}"


def dataframe_manifest_key(
    *, project_id: str, node_id: str, output_name: str, generation_id: str
) -> str:
    return f"df:{project_id}:{node_id}:{output_name}:{generation_id}:manifest"


def dataframe_snapshot_key(*, project_id: str, node_id: str, generation_id: str) -> str:
    return f"df:{project_id}:{node_id}:{generation_id}:snapshot"


def dataframe_active_key(*, project_id: str, node_id: str) -> str:
    return f"df:{project_id}:{node_id}:active"
