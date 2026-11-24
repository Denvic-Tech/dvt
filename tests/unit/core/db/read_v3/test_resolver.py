from __future__ import annotations

import pytest
import sqlalchemy as sa

from core.db.read_v3 import resolver
from core.db.read_v3.errors import ReadV3ConfigError, ReadV3DialectError
from core.db.read_v3.executors.pg import PostgresReadExecutor
from core.db.read_v3.executors.sql import SQLReadExecutor
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


def test_resolver_uses_postgres_executor_only_with_adbc_and_the_switch_on(monkeypatch):
    engine = sa.create_engine("postgresql+psycopg://u:p@localhost/db")
    monkeypatch.setattr(resolver, "adbc_available", lambda: True)
    assert isinstance(resolver.resolve_executor(engine), PostgresReadExecutor)
    assert type(resolver.resolve_executor(engine, pg_arrow_read=False)) is SQLReadExecutor
    monkeypatch.setattr(resolver, "adbc_available", lambda: False)
    assert type(resolver.resolve_executor(engine)) is SQLReadExecutor
    sqlite = sa.create_engine("sqlite://")
    monkeypatch.setattr(resolver, "adbc_available", lambda: True)
    assert type(resolver.resolve_executor(sqlite)) is SQLReadExecutor
