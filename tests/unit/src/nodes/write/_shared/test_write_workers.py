from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from core.db import concurrency

from src.nodes.write._shared.write_workers import (
    LEGACY_WRITE_CHUNK_ROWS,
    resolve_bulk_write_workers,
    resolve_write_chunksize,
    resolve_write_workers,
)

import config


def _engine(dialect_name: str) -> SimpleNamespace:
    return SimpleNamespace(dialect=SimpleNamespace(name=dialect_name))


def _project(workers_count: int | None) -> SimpleNamespace:
    return SimpleNamespace(workers_count=workers_count)


@pytest.fixture(autouse=True)
def _concurrency_config(monkeypatch):
    monkeypatch.setattr(config.OTHER, "DB_CONCURRENCY_POLICY", "dialect")
    monkeypatch.setattr(config.OTHER, "DB_WRITE_WORKERS_OVERRIDES", {})
    monkeypatch.setattr(config.OTHER, "BULK_INSERT_NUM_WORKERS", 8)
    monkeypatch.setattr(config.OTHER, "SQL_BULK_INSERT_MAX_WORKERS", 32)


def _patch_defaults(monkeypatch, **write_workers: int) -> None:
    # Table values are placeholders: tests pin their own so tuning them never breaks a test.
    for dialect, workers in write_workers.items():
        current = concurrency.DIALECT_CONCURRENCY[dialect]
        monkeypatch.setitem(
            concurrency.DIALECT_CONCURRENCY,
            dialect,
            concurrency.DialectConcurrency(
                write_workers=workers, read_queries=current.read_queries
            ),
        )


def test_project_workers_count_wins_over_dialect_and_legacy(monkeypatch) -> None:
    _patch_defaults(monkeypatch, postgresql=1)

    assert resolve_write_workers(_project(4), _engine("postgresql")) == 4


@pytest.mark.parametrize("workers_count", [None, 0])
def test_dialect_policy_uses_dialect_default_without_project_setting(
    monkeypatch, workers_count
) -> None:
    _patch_defaults(monkeypatch, postgresql=1, clickhouse=6)

    assert resolve_write_workers(_project(workers_count), _engine("postgresql")) == 1
    assert resolve_write_workers(_project(workers_count), _engine("clickhouse")) == 6


def test_dialect_env_override_replaces_the_default(monkeypatch) -> None:
    _patch_defaults(monkeypatch, postgresql=1)
    monkeypatch.setattr(config.OTHER, "DB_WRITE_WORKERS_OVERRIDES", {"postgresql": 3})

    assert resolve_write_workers(_project(0), _engine("postgresql")) == 3


def test_legacy_policy_keeps_bulk_insert_num_workers(monkeypatch) -> None:
    _patch_defaults(monkeypatch, postgresql=1)
    monkeypatch.setattr(config.OTHER, "DB_CONCURRENCY_POLICY", "legacy")

    assert resolve_write_workers(_project(0), _engine("postgresql")) == 8
    assert resolve_write_workers(_project(2), _engine("postgresql")) == 2


def test_unknown_dialect_falls_back_to_legacy_workers() -> None:
    assert resolve_write_workers(_project(0), _engine("snowflake")) == 8


def test_every_source_is_capped_by_max_workers(monkeypatch) -> None:
    _patch_defaults(monkeypatch, clickhouse=16)
    monkeypatch.setattr(config.OTHER, "SQL_BULK_INSERT_MAX_WORKERS", 5)

    assert resolve_write_workers(_project(12), _engine("postgresql")) == 5
    assert resolve_write_workers(_project(0), _engine("clickhouse")) == 5
    monkeypatch.setattr(config.OTHER, "DB_CONCURRENCY_POLICY", "legacy")
    assert resolve_write_workers(_project(0), _engine("clickhouse")) == 5


def _patch_bulk(monkeypatch, **bulk_workers: int | None) -> None:
    for dialect, workers in bulk_workers.items():
        current = concurrency.DIALECT_CONCURRENCY[dialect]
        monkeypatch.setitem(
            concurrency.DIALECT_CONCURRENCY,
            dialect,
            replace(current, bulk_write_workers=workers),
        )


@pytest.mark.parametrize("workers_count", [None, 0])
def test_bulk_workers_use_the_dialect_bulk_default(monkeypatch, workers_count) -> None:
    _patch_bulk(monkeypatch, postgresql=4)
    # An override of another dialect does not touch this one.
    monkeypatch.setattr(config.OTHER, "DB_WRITE_WORKERS_OVERRIDES", {"mysql": 2})

    assert resolve_bulk_write_workers(_project(workers_count), _engine("postgresql")) == 4


def test_explicit_worker_settings_disable_bulk_workers(monkeypatch) -> None:
    _patch_bulk(monkeypatch, postgresql=4)

    assert resolve_bulk_write_workers(_project(2), _engine("postgresql")) is None
    monkeypatch.setattr(config.OTHER, "DB_WRITE_WORKERS_OVERRIDES", {"postgresql": 1})
    assert resolve_bulk_write_workers(_project(0), _engine("postgresql")) is None
    monkeypatch.setattr(config.OTHER, "DB_WRITE_WORKERS_OVERRIDES", {})
    monkeypatch.setattr(config.OTHER, "DB_CONCURRENCY_POLICY", "legacy")
    assert resolve_bulk_write_workers(_project(0), _engine("postgresql")) is None


def test_bulk_workers_are_capped_by_max_workers(monkeypatch) -> None:
    _patch_bulk(monkeypatch, postgresql=4)
    monkeypatch.setattr(config.OTHER, "SQL_BULK_INSERT_MAX_WORKERS", 3)

    assert resolve_bulk_write_workers(_project(0), _engine("postgresql")) == 3


def test_dialects_without_a_bulk_path_have_no_bulk_workers(monkeypatch) -> None:
    _patch_bulk(monkeypatch, clickhouse=None)

    assert resolve_bulk_write_workers(_project(0), _engine("clickhouse")) is None
    assert resolve_bulk_write_workers(_project(0), _engine("snowflake")) is None


def _patch_chunk_rows(monkeypatch, **chunk_rows: int) -> None:
    for dialect, rows in chunk_rows.items():
        current = concurrency.DIALECT_CONCURRENCY[dialect]
        monkeypatch.setitem(
            concurrency.DIALECT_CONCURRENCY,
            dialect,
            concurrency.DialectConcurrency(
                write_workers=current.write_workers,
                read_queries=current.read_queries,
                write_chunk_rows=rows,
            ),
        )


@pytest.mark.parametrize("policy", ["dialect", "legacy"])
def test_node_chunksize_wins_over_dialect_default(monkeypatch, policy) -> None:
    _patch_chunk_rows(monkeypatch, clickhouse=50_000)
    monkeypatch.setattr(config.OTHER, "DB_CONCURRENCY_POLICY", policy)

    assert resolve_write_chunksize(250, _engine("clickhouse")) == 250


def test_dialect_policy_uses_dialect_chunk_rows_without_node_chunksize(monkeypatch) -> None:
    _patch_chunk_rows(monkeypatch, clickhouse=50_000, postgresql=700)

    assert resolve_write_chunksize(None, _engine("clickhousedb")) == 50_000
    assert resolve_write_chunksize(None, _engine("postgresql")) == 700


def test_legacy_policy_and_unknown_dialect_use_legacy_chunk_rows(monkeypatch) -> None:
    _patch_chunk_rows(monkeypatch, clickhouse=50_000)

    assert resolve_write_chunksize(None, _engine("snowflake")) == LEGACY_WRITE_CHUNK_ROWS
    monkeypatch.setattr(config.OTHER, "DB_CONCURRENCY_POLICY", "legacy")
    assert resolve_write_chunksize(None, _engine("clickhouse")) == LEGACY_WRITE_CHUNK_ROWS
