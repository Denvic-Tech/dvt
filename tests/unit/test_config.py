from __future__ import annotations

import pytest

import config


def test_dialect_overrides_read_only_known_dialect_suffixes(monkeypatch) -> None:
    monkeypatch.setenv("DB_WRITE_WORKERS_POSTGRESQL", "2")
    monkeypatch.setenv("DB_WRITE_WORKERS_CLICKHOUSE", "12")
    monkeypatch.setenv("DB_WRITE_WORKERS_POSTGRES", "5")  # not a table key: ignored
    monkeypatch.setenv("DB_WRITE_WORKERS_MSSQL", "")  # empty: no override

    overrides = config._get_dialect_positive_int_envs("DB_WRITE_WORKERS_")

    assert overrides == {"postgresql": 2, "clickhouse": 12}


@pytest.mark.parametrize("value", ["0", "-1"])
def test_dialect_overrides_reject_non_positive_values(monkeypatch, value) -> None:
    monkeypatch.setenv("DB_READ_CONCURRENCY_MSSQL", value)

    with pytest.raises(ValueError, match="DB_READ_CONCURRENCY_MSSQL"):
        config._get_dialect_positive_int_envs("DB_READ_CONCURRENCY_")
