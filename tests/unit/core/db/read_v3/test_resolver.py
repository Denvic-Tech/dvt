from __future__ import annotations

import pytest

from core.db.read_v3.errors import ReadV3ConfigError, ReadV3DialectError
from core.db.read_v3.resolver import resolve_executor, resolve_planner


class _Dialect:
    def __init__(self, name: str):
        self.name = name


class _Engine:
    def __init__(self, name: str):
        self.dialect = _Dialect(name)


def test_resolver_returns_planners() -> None:
    assert resolve_planner("table").__class__.__name__ == "TableReadPlanner"
    assert resolve_planner("query").__class__.__name__ == "QueryReadPlanner"


def test_resolver_rejects_unknown_mode() -> None:
    with pytest.raises(ReadV3ConfigError):
        resolve_planner("invalid")


def test_resolver_rejects_unknown_dialect() -> None:
    engine = _Engine("snowflake")
    with pytest.raises(ReadV3DialectError):
        resolve_executor(engine)
