from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest
from tests.fixtures.percent_format_sqlite import percent_format_sqlite_engine

from core.db.read_v3.sql_runner import (
    ClickHouseReadV3SqlRunner,
    SqlAlchemyReadV3SqlRunner,
    resolve_sql_runner,
)


@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        ("SELECT 'A%' AS v", ["A%"]),
        # A doubled percent sign is two characters, as in psql or the mysql client.
        ("SELECT '%%' AS v", ["%%"]),
        ("SELECT 7 % 3 AS v", [1]),
        ("SELECT 'x%sy' AS v", ["x%sy"]),
    ],
)
def test_sqlalchemy_runner_sends_percent_sql_to_the_driver_unchanged(sql, expected) -> None:
    calls: list[tuple[str, object]] = []
    engine = percent_format_sqlite_engine(":memory:", calls)

    df = SqlAlchemyReadV3SqlRunner(engine).query_df(sql)

    assert df["v"].tolist() == expected
    # The text reaches cursor.execute without a parameter collection.
    assert calls[-1] == (sql, None)


class _FakeClickHouseEngine:
    dialect = SimpleNamespace(name="clickhouse")
    url = SimpleNamespace(
        drivername="clickhouse+http",
        query={},
        port=8123,
        host="localhost",
        username="default",
        password="",
        database="default",
    )


class _FakeClickHouseClient:
    def __init__(self) -> None:
        self.queries: list[str] = []
        self.closed = False

    def query_df(self, sql: str) -> pd.DataFrame:
        self.queries.append(sql)
        if sql.startswith("DESCRIBE TABLE"):
            return pd.DataFrame(
                {
                    "name": ["id", "label"],
                    "type": ["Int64", "Nullable(String)"],
                }
            )
        return pd.DataFrame({"id": [1], "label": ["Демо"]})

    def close(self) -> None:
        self.closed = True


def test_clickhouse_runner_sends_percent_query_through_clickhouse_client(monkeypatch) -> None:
    client = _FakeClickHouseClient()
    factory_calls: list[dict[str, object]] = []

    def _create_client(client_kwargs):
        factory_calls.append(dict(client_kwargs))
        return client

    monkeypatch.setattr("core.db.read_v3.sql_runner.create_clickhouse_client", _create_client)

    runner = resolve_sql_runner(_FakeClickHouseEngine())
    df = runner.query_df("SELECT formatDateTime(now(), '%Y-%m-%d') AS day WHERE 'Д' LIKE '%Д%'")

    assert isinstance(runner, ClickHouseReadV3SqlRunner)
    assert factory_calls == [
        {
            "host": "localhost",
            "port": 8123,
            "username": "default",
            "password": "",
            "database": "default",
            "secure": False,
            "interface": "http",
        }
    ]
    assert df["label"].tolist() == ["Демо"]
    assert client.queries == [
        "SELECT formatDateTime(now(), '%Y-%m-%d') AS day WHERE 'Д' LIKE '%Д%'"
    ]
    assert client.closed is True


def test_clickhouse_runner_describes_query_columns(monkeypatch) -> None:
    client = _FakeClickHouseClient()
    monkeypatch.setattr(
        "core.db.read_v3.sql_runner.create_clickhouse_client",
        lambda _client_kwargs: client,
    )

    runner = resolve_sql_runner(_FakeClickHouseEngine())
    columns = runner.describe_query_columns("SELECT id, label FROM demo")

    assert columns == [("id", "Int64"), ("label", "Nullable(String)")]
    assert client.queries == ["DESCRIBE TABLE (SELECT id, label FROM demo)"]
    assert client.closed is True


def test_clickhouse_runner_closes_client_when_query_fails(monkeypatch) -> None:
    client = _FakeClickHouseClient()

    def _raise_query_error(_sql: str) -> pd.DataFrame:
        raise RuntimeError("query failed")

    client.query_df = _raise_query_error
    monkeypatch.setattr(
        "core.db.read_v3.sql_runner.create_clickhouse_client",
        lambda _client_kwargs: client,
    )

    runner = resolve_sql_runner(_FakeClickHouseEngine())

    with pytest.raises(RuntimeError, match="query failed"):
        runner.query_df("SELECT broken")

    assert client.closed is True

