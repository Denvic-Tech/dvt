from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_module():
    module_path = (
        Path(__file__).resolve().parents[4]
        / "migrations"
        / "versions"
        / "0043_add_node_task_source.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0043", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to load migration module 0043")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _ScalarResult:
    def __init__(self, values):
        self._values = values

    def all(self):
        return list(self._values)


class _FakeExecuteResult:
    def __init__(self, values):
        self._values = values

    def scalars(self):
        return _ScalarResult(self._values)


class _FakeBind:
    def __init__(self, values):
        self._values = values

    def execute(self, _query):
        return _FakeExecuteResult(self._values)


def test_fetch_non_legacy_task_sources_returns_sorted_distinct_values() -> None:
    migration = _load_module()

    bind = _FakeBind(["MANUAL", "NODE", "SERVICE"])

    assert migration._fetch_non_legacy_task_sources(bind) == ["MANUAL", "NODE", "SERVICE"]
