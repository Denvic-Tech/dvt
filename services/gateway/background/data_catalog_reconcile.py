"""Фоновая сверка проекций Data Catalog после старта Gateway.

Закрывает пробел раскатки: проекты, сохранённые до появления каталога или до бампа
LINEAGE_SCHEMA_VERSION, получают проекции без ручного backfill. Одна реплика Gateway
удерживает advisory lock на время сверки, остальные пропускают прогон. Любая ошибка
логируется и не влияет на работу сервиса.
"""

from __future__ import annotations

import asyncio
import contextlib
import time

import sqlalchemy as sa
from fastapi import FastAPI

from src.logger import logger
from src.modules.data_catalog.domain import ReconcileSummary

import config

_TASK_STATE_ATTR = "data_catalog_reconcile_task"


async def run_data_catalog_reconciliation() -> ReconcileSummary | None:
    """Возвращает итог сверки или None, если прогон пропущен или упал."""
    from src.db import AsyncSessionLocal, async_engine
    from src.modules.data_catalog import reconcile_catalog_projections

    lock_key = config.DATA_CATALOG.RECONCILE_ADVISORY_LOCK_KEY
    started = time.monotonic()
    try:
        async with async_engine.connect() as lock_connection:
            use_lock = lock_connection.dialect.name == "postgresql"
            if use_lock and not await _try_advisory_lock(lock_connection, lock_key):
                logger.info(
                    "Data catalog reconcile skipped: advisory lock {} is held by another instance",
                    lock_key,
                )
                return None
            try:
                summary = await reconcile_catalog_projections(
                    session_factory=AsyncSessionLocal,
                    batch_size=config.DATA_CATALOG.STARTUP_RECONCILE_BATCH_SIZE,
                )
            finally:
                if use_lock:
                    await _advisory_unlock(lock_connection, lock_key)
    except asyncio.CancelledError:
        logger.info("Data catalog reconcile cancelled on shutdown")
        raise
    except Exception:
        logger.exception("Data catalog reconcile failed")
        return None

    logger.info(
        "Data catalog reconcile done in {:.1f}s: total={} ok={} skipped={} failed={}",
        time.monotonic() - started,
        summary.total,
        summary.ok,
        summary.skipped,
        summary.failed,
    )
    for project_id, error in summary.failures:
        logger.warning("Data catalog reconcile: project {} failed: {}", project_id, error)
    return summary


async def _try_advisory_lock(connection, key: int) -> bool:
    result = await connection.execute(sa.text("SELECT pg_try_advisory_lock(:k)"), {"k": key})
    return bool(result.scalar())


async def _advisory_unlock(connection, key: int) -> None:
    try:
        await connection.execute(sa.text("SELECT pg_advisory_unlock(:k)"), {"k": key})
    except Exception:
        logger.warning("Data catalog reconcile: failed to release advisory lock {}", key)


def start_data_catalog_reconciliation(app: FastAPI) -> asyncio.Task:
    task = asyncio.create_task(run_data_catalog_reconciliation(), name="data-catalog-reconcile")
    setattr(app.state, _TASK_STATE_ATTR, task)
    return task


async def stop_data_catalog_reconciliation(app: FastAPI) -> None:
    task: asyncio.Task | None = getattr(app.state, _TASK_STATE_ATTR, None)
    if task is None or task.done():
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await task
