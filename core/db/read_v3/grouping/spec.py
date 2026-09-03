from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping, Optional


class GroupingSpecError(ValueError):
    pass


@dataclass(frozen=True)
class GroupingSpec:
    mode: str
    params: dict[str, Any]

    @classmethod
    def parse(cls, raw: Optional[object]) -> Optional["GroupingSpec"]:
        if raw is None:
            return None
        if isinstance(raw, GroupingSpec):
            return raw
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise GroupingSpecError(
                    "partition_grouping must be a dict or valid JSON string"
                ) from exc
        if not isinstance(raw, Mapping):
            raise GroupingSpecError("partition_grouping must be a dict or GroupingSpec")
        mode = raw.get("mode") or raw.get("type")
        if not mode:
            raise GroupingSpecError("partition_grouping.mode is required")
        params = {key: value for key, value in raw.items() if key not in ("mode", "type")}
        return GroupingSpec(mode=str(mode).strip().lower(), params=dict(params))
