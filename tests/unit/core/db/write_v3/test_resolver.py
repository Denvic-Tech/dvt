from __future__ import annotations

import pytest

from core.db.write_v3.errors import WriteV3DialectError
from core.db.write_v3.resolver import resolve_executor


class _Dialect:
    def __init__(self, name: str):
        self.name = name


class _Engine:
    def __init__(self, name: str):
        self.dialect = _Dialect(name)


def test_resolver_returns_sql_executor_for_sqlite() -> None:
    executor = resolve_executor(_Engine("sqlite"))
    assert executor.__class__.__name__ == "SQLWriteExecutor"


def test_resolver_returns_clickhouse_executor() -> None:
    executor = resolve_executor(_Engine("clickhouse"))
    assert executor.__class__.__name__ == "ClickHouseWriteExecutor"


def test_resolver_rejects_unknown_dialect() -> None:
    with pytest.raises(WriteV3DialectError):
        resolve_executor(_Engine("snowflake"))
