from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional, Sequence


class ValueKind(str, Enum):
    STRING = "string"
    DATE = "date"
    DATETIME = "datetime"
    NUMERIC = "numeric"
    BOOL = "bool"
    UNKNOWN = "unknown"


@dataclass
class PartitionSegment:
    """Grouping-oriented partition filter description."""

    label: str
    include_values: Optional[Sequence[Any]] = None
    exclude_values: Optional[Sequence[Any]] = None
    range_start: Optional[Any] = None
    range_end: Optional[Any] = None
    is_null: bool = False
    count: Optional[int] = None
    include_end: bool = False
    hash_mod: Optional[int] = None
    buckets: Optional[Sequence[int]] = None
    offset: Optional[int] = None
    page_size: Optional[int] = None
    value_expr: Optional[str] = None

    def merge_with(self, other: "PartitionSegment") -> "PartitionSegment":
        """Merge two compatible segments while keeping deterministic labels and counts."""
        if self.value_expr and other.value_expr and self.value_expr != other.value_expr:
            raise ValueError("Cannot merge segments with different value expressions")

        merged_include = None
        if self.include_values is not None or other.include_values is not None:
            merged_include = []
            if self.include_values:
                merged_include.extend(self.include_values)
            if other.include_values:
                merged_include.extend(other.include_values)

        merged_exclude = None
        if self.exclude_values is not None or other.exclude_values is not None:
            merged_exclude = []
            if self.exclude_values:
                merged_exclude.extend(self.exclude_values)
            if other.exclude_values:
                merged_exclude.extend(other.exclude_values)

        return PartitionSegment(
            label=f"{self.label}+{other.label}",
            include_values=merged_include,
            exclude_values=merged_exclude,
            range_start=self.range_start,
            range_end=other.range_end,
            is_null=self.is_null or other.is_null,
            count=(self.count or 0) + (other.count or 0),
            include_end=self.include_end or other.include_end,
            value_expr=self.value_expr or other.value_expr,
        )
