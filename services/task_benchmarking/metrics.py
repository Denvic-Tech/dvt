"""Process-wide store of metrics reported by benchmark nodes.

Nodes call ``record_metric`` while the pipeline runs; the report reads ``get_metrics`` after the
run. The runner calls ``reset`` before every pipeline run, so metrics never leak between runs.
"""

from __future__ import annotations

import threading
from typing import Any

_LOCK = threading.Lock()
_METRICS: dict[str, dict[str, Any]] = {}


def record_metric(node_id: str, key: str, value: Any) -> None:
    with _LOCK:
        _METRICS.setdefault(node_id, {})[key] = value


def get_metrics() -> dict[str, dict[str, Any]]:
    with _LOCK:
        return {node_id: dict(values) for node_id, values in _METRICS.items()}


def reset() -> None:
    with _LOCK:
        _METRICS.clear()
