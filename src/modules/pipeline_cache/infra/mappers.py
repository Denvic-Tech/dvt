from __future__ import annotations

from ..domain.entities import MetadataCacheEntry


def build_metadata_cache_entry(
    *,
    outputs: dict[str, object],
    metadata: dict[str, object] | None,
) -> MetadataCacheEntry:
    return MetadataCacheEntry.create(outputs=outputs, metadata=metadata)
