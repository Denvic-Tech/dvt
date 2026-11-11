from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.db import concurrency

from src.nodes.extract._shared.read_concurrency import resolve_read_concurrency

import config


def _engine(dialect_name: str) -> SimpleNamespace:
    return SimpleNamespace(dialect=SimpleNamespace(name=dialect_name))


@pytest.fixture(autouse=True)
def _concurrency_config(monkeypatch):
    monkeypatch.setattr(config.OTHER, "DB_CONCURRENCY_POLICY", "dialect")
    monkeypatch.setattr(config.OTHER, "DB_READ_CONCURRENCY_OVERRIDES", {})
    # Table values are placeholders: pin them so tuning never breaks these tests.
    monkeypatch.setitem(
        concurrency.DIALECT_CONCURRENCY,
        "mssql",
        concurrency.DialectConcurrency(write_workers=1, read_queries=1),
    )


def test_explicit_node_value_wins_under_both_policies(monkeypatch) -> None:
    assert resolve_read_concurrency(4, _engine("mssql")) == 4
    monkeypatch.setattr(config.OTHER, "DB_CONCURRENCY_POLICY", "legacy")
    assert resolve_read_concurrency(4, _engine("mssql")) == 4


def test_dialect_policy_uses_default_and_env_override(monkeypatch) -> None:
    assert resolve_read_concurrency(None, _engine("mssql")) == 1
    monkeypatch.setattr(config.OTHER, "DB_READ_CONCURRENCY_OVERRIDES", {"mssql": 3})
    assert resolve_read_concurrency(None, _engine("mssql")) == 3


def test_legacy_policy_and_unknown_dialect_keep_reads_unlimited(monkeypatch) -> None:
    assert resolve_read_concurrency(None, _engine("snowflake")) is None
    monkeypatch.setattr(config.OTHER, "DB_CONCURRENCY_POLICY", "legacy")
    assert resolve_read_concurrency(None, _engine("mssql")) is None
