from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI

from services.gateway.background import data_catalog_reconcile as module

from src.modules.data_catalog.domain import ReconcileSummary


class _Result:
    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value


class _Connection:
    def __init__(self, *, dialect: str = "postgresql", lock_acquired: bool = True) -> None:
        self.dialect = SimpleNamespace(name=dialect)
        self.lock_acquired = lock_acquired
        self.statements: list[str] = []

    async def execute(self, statement, params=None):
        text = str(statement)
        self.statements.append(text)
        if "pg_try_advisory_lock" in text:
            return _Result(self.lock_acquired)
        return _Result(True)


class _Engine:
    def __init__(self, connection: _Connection) -> None:
        self.connection = connection

    def connect(self):
        connection = self.connection

        class _Ctx:
            async def __aenter__(self):
                return connection

            async def __aexit__(self, *exc_info):
                return False

        return _Ctx()


def _install(monkeypatch, connection: _Connection, reconcile):
    import src.db
    from src.modules import data_catalog

    monkeypatch.setattr(src.db, "async_engine", _Engine(connection))
    monkeypatch.setattr(src.db, "AsyncSessionLocal", object())
    monkeypatch.setattr(data_catalog, "reconcile_catalog_projections", reconcile)


@pytest.mark.asyncio
async def test_runs_reconcile_under_advisory_lock_and_releases_it(monkeypatch):
    connection = _Connection()
    summary = ReconcileSummary(total=2, ok=1, failed=1, failures=[("p", "boom")])
    reconcile = AsyncMock(return_value=summary)
    _install(monkeypatch, connection, reconcile)
    monkeypatch.setattr(module.config.DATA_CATALOG, "STARTUP_RECONCILE_BATCH_SIZE", 7)

    result = await module.run_data_catalog_reconciliation()

    assert result is summary
    assert reconcile.await_args.kwargs["batch_size"] == 7
    assert any("pg_try_advisory_lock" in s for s in connection.statements)
    assert any("pg_advisory_unlock" in s for s in connection.statements)


@pytest.mark.asyncio
async def test_skips_when_lock_is_held_elsewhere(monkeypatch):
    connection = _Connection(lock_acquired=False)
    reconcile = AsyncMock()
    _install(monkeypatch, connection, reconcile)

    result = await module.run_data_catalog_reconciliation()

    assert result is None
    reconcile.assert_not_awaited()
    assert not any("pg_advisory_unlock" in s for s in connection.statements)


@pytest.mark.asyncio
async def test_non_postgres_dialect_runs_without_lock(monkeypatch):
    connection = _Connection(dialect="sqlite")
    reconcile = AsyncMock(return_value=ReconcileSummary())
    _install(monkeypatch, connection, reconcile)

    result = await module.run_data_catalog_reconciliation()

    assert result is not None
    assert connection.statements == []


@pytest.mark.asyncio
async def test_failures_are_swallowed_and_lock_released(monkeypatch):
    connection = _Connection()
    reconcile = AsyncMock(side_effect=RuntimeError("catalog down"))
    _install(monkeypatch, connection, reconcile)

    result = await module.run_data_catalog_reconciliation()

    assert result is None
    assert any("pg_advisory_unlock" in s for s in connection.statements)


@pytest.mark.asyncio
async def test_start_and_stop_manage_the_background_task(monkeypatch):
    started = asyncio.Event()

    async def _forever():
        started.set()
        await asyncio.sleep(3600)

    monkeypatch.setattr(module, "run_data_catalog_reconciliation", _forever)
    app = FastAPI()

    task = module.start_data_catalog_reconciliation(app)
    await started.wait()
    await module.stop_data_catalog_reconciliation(app)

    assert task.cancelled()
    await module.stop_data_catalog_reconciliation(app)
    await module.stop_data_catalog_reconciliation(FastAPI())
