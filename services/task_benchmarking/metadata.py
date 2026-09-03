from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any


def _json_safe(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {str(key): _json_safe(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def serialize_metadata(metadata: Any) -> Any:
    return _json_safe(metadata)


def dumps_metadata(metadata: Any, *, indent: int = 2) -> str:
    return json.dumps(serialize_metadata(metadata), indent=indent, ensure_ascii=True, default=str)


def metadata_metrics(metadata: Any) -> dict[str, int]:
    payload = serialize_metadata(metadata)
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    counts = {"databases": 0, "schemas": 0, "tables": 0, "columns": 0}

    def visit(value: Any) -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                if key in counts and isinstance(child, list):
                    counts[key] += len(child)
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(payload)
    return {"payload_bytes": len(encoded), **counts}
