from __future__ import annotations

from typing import Iterable

from core.db.read_v3.grouping.models import PartitionSegment


def pack_segments(segments: Iterable[PartitionSegment], bins: int) -> list[PartitionSegment]:
    """
    Greedy pack segments to reduce fan-out while preserving special buckets.

    This intentionally mirrors legacy read_v2 behavior so grouping plans stay stable.
    """
    pool = list(segments)
    if len(pool) <= bins:
        return pool

    preserved = [segment for segment in pool if segment.is_null or segment.exclude_values is not None]
    pool = [segment for segment in pool if segment not in preserved]

    pool.sort(key=lambda segment: segment.count or 0)
    while len(pool) > max(1, bins - len(preserved)):
        first = pool.pop(0)
        second = pool.pop(0)
        pool.append(first.merge_with(second))
        pool.sort(key=lambda segment: segment.count or 0)

    return pool + preserved
