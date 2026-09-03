from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_module():
    module_path = (
        Path(__file__).resolve().parents[4]
        / "migrations"
        / "versions"
        / "0041_normalize_task_source_values.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0041", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to load migration module 0041")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_task_source_updates_normalizes_known_legacy_values() -> None:
    migration = _load_module()

    rows = [
        {"task_id": "task-api", "source": "api"},
        {"task_id": "task-ui", "source": " ui "},
        {"task_id": "task-scheduler", "source": "SCHEDULER"},
        {"task_id": "task-empty", "source": ""},
        {"task_id": "task-none", "source": None},
    ]

    assert migration._build_task_source_updates(rows, uppercase=True) == [
        {"task_id": "task-api", "source": "API"},
        {"task_id": "task-ui", "source": "UI"},
    ]


def test_collect_unexpected_task_sources_returns_only_unsupported_values() -> None:
    migration = _load_module()

    rows = [
        {"task_id": "task-api", "source": "api"},
        {"task_id": "task-ui", "source": "UI"},
        {"task_id": "task-bad", "source": "service"},
        {"task_id": "task-other", "source": "manual"},
        {"task_id": "task-none", "source": None},
    ]

    assert migration._collect_unexpected_task_sources(rows) == ["manual", "service"]
