from __future__ import annotations

import pytest

from core.db.concurrency import (
    DIALECT_CONCURRENCY,
    dialect_bulk_write_workers,
    dialect_key,
    dialect_read_concurrency,
    dialect_write_chunk_rows,
    dialect_write_workers,
)


@pytest.mark.parametrize(
    ("dialect_name", "expected"),
    [
        ("postgresql", "postgresql"),
        ("mssql", "mssql"),
        ("mysql", "mysql"),
        ("mariadb", "mysql"),
        ("MariaDB", "mysql"),
        ("clickhouse", "clickhouse"),
        ("clickhousedb", "clickhouse"),
        ("oracle", "oracle"),
        ("sqlite", "sqlite"),
        ("snowflake", None),
        (None, None),
    ],
)
def test_dialect_key_follows_read_and_write_dialect_matching(dialect_name, expected) -> None:
    assert dialect_key(dialect_name) == expected


def test_every_table_key_is_reachable_from_its_own_dialect_name() -> None:
    assert all(dialect_key(key) == key for key in DIALECT_CONCURRENCY)


def test_overrides_win_per_dialect_and_mariadb_uses_the_mysql_entry() -> None:
    write_overrides = {"postgresql": 3}
    read_overrides = {"mysql": 4}

    assert dialect_write_workers("postgresql", write_overrides) == 3
    mssql_default = DIALECT_CONCURRENCY["mssql"].write_workers
    assert dialect_write_workers("mssql", write_overrides) == mssql_default
    assert dialect_read_concurrency("mariadb", read_overrides) == 4


def test_unknown_dialect_has_no_default() -> None:
    assert dialect_write_workers("snowflake", {"snowflake": 5}) is None
    assert dialect_read_concurrency("snowflake") is None


def test_write_chunk_rows_follow_the_dialect_table() -> None:
    clickhouse_rows = DIALECT_CONCURRENCY["clickhouse"].write_chunk_rows

    assert dialect_write_chunk_rows("clickhousedb") == clickhouse_rows
    assert dialect_write_chunk_rows("mariadb") == DIALECT_CONCURRENCY["mysql"].write_chunk_rows
    assert dialect_write_chunk_rows("snowflake") is None
    assert dialect_write_chunk_rows(None) is None


def test_bulk_write_workers_exist_only_for_dialects_with_a_bulk_path() -> None:
    postgres_bulk = DIALECT_CONCURRENCY["postgresql"].bulk_write_workers

    assert postgres_bulk is not None
    assert postgres_bulk > DIALECT_CONCURRENCY["postgresql"].write_workers
    assert dialect_bulk_write_workers("postgresql") == postgres_bulk
    assert dialect_bulk_write_workers("clickhousedb") is None
    assert dialect_bulk_write_workers("snowflake") is None
