from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass(slots=True)
class ResourcePreset:
    name: str
    global_input_overrides: dict[str, Any]
    sample_interval: Optional[float] = None


RESOURCE_PRESETS: dict[str, ResourcePreset] = {
    "ram_8g": ResourcePreset(
        name="ram_8g",
        global_input_overrides={
            "npartitions": 64,
            "num_workers": 2,
            "max_rows_per_partition": 1_500_000,
        },
        sample_interval=0.2,
    ),
    "ram_16g": ResourcePreset(
        name="ram_16g",
        global_input_overrides={
            "npartitions": 96,
            "num_workers": 4,
            "max_rows_per_partition": 2_500_000,
        },
        sample_interval=0.15,
    ),
}


def resolve_preset(name: Optional[str]) -> Optional[ResourcePreset]:
    if not name:
        return None
    preset = RESOURCE_PRESETS.get(name)
    if preset is None:
        raise ValueError(f"Unknown preset: {name}")
    return preset


def cli_global_input_overrides(
    *,
    npartitions: Optional[int],
    num_workers: Optional[int],
    max_rows_per_partition: Optional[int],
) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    if npartitions is not None:
        overrides["npartitions"] = npartitions
    if num_workers is not None:
        overrides["num_workers"] = num_workers
    if max_rows_per_partition is not None:
        overrides["max_rows_per_partition"] = max_rows_per_partition
    return overrides


def merge_global_overrides(*values: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for value in values:
        merged.update(value)
    return merged
