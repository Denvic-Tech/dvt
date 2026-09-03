from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Iterable
from typing import Any


@dataclass(frozen=True, slots=True)
class MetadataCacheEntry:
    outputs: dict[str, Any]
    metadata: dict[str, Any] | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "outputs", dict(self.outputs))
        object.__setattr__(
            self,
            "metadata",
            None if self.metadata is None else dict(self.metadata),
        )

    @classmethod
    def create(
        cls,
        *,
        outputs: dict[str, Any],
        metadata: dict[str, Any] | None,
    ) -> MetadataCacheEntry:
        return cls(outputs=outputs, metadata=metadata)

    def normalized_for_outputs(
        self,
        expected_output_names: Iterable[str],
    ) -> MetadataCacheEntry | None:
        ordered_output_names = list(expected_output_names)
        definition_names = set(ordered_output_names)
        cached_output_names = set(self.outputs.keys())
        if definition_names != cached_output_names:
            return None

        cached_metadata = self.metadata or {}
        if not set(cached_metadata.keys()).issubset(definition_names):
            return None

        return type(self).create(
            outputs=self.outputs,
            metadata={
                output_name: cached_metadata.get(output_name)
                for output_name in ordered_output_names
            },
        )


@dataclass(frozen=True, slots=True)
class JSONCacheEntry:
    data: Any


@dataclass(frozen=True, slots=True)
class DataIndexEntry:
    cache_key: str
    output_name: str


@dataclass(frozen=True, slots=True)
class DDFMetaIndexEntry(DataIndexEntry):
    hashed_inputs: dict[str, bytes] | None = None


@dataclass(frozen=True, slots=True)
class PDFIndexEntry(DataIndexEntry):
    part_no: int
    total_parts: int
    rows: int


@dataclass(frozen=True, slots=True)
class ClearCacheResult:
    cleared_keys: list[str]
    task_id: str | None = None


@dataclass(frozen=True, slots=True)
class GetJsonEntryResult:
    data: Any
    total_items: int | None


@dataclass(frozen=True, slots=True)
class GetDataFrameEntryResult:
    dataframe: Any
    total_rows: int
    total_partitions: int


@dataclass(frozen=True, slots=True)
class RestoreMetadataEntryResult:
    restored: bool
    entry: MetadataCacheEntry | None = None
