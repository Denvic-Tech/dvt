from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable

import aiohttp

from src.clients.scheduler_client import SchedulerClient
from src.db import AsyncSessionLocal
from src.logger import logger
from src.managers.system_info_manager import SystemInfoManager
from src.runtime.async_runtime import shared_orchestrator

import config

from .cache import MetricsCache
from .collectors import (
    collect_adoption_metrics,
    collect_pipeline_metrics,
    collect_queue_metrics,
    collect_schedule_metrics,
    collect_system_metrics,
    collect_worker_metrics,
)
from .collectors.common import CollectorResult


class MetricsUpdaterManager:
    def __init__(self, cache: MetricsCache) -> None:
        self.cache = cache
        self._tasks: list[asyncio.Task] = []
        self._stop_event = asyncio.Event()
        self._collector_locks: dict[str, asyncio.Lock] = {}
        self._system_info_manager = SystemInfoManager()
        self._scheduler_session: aiohttp.ClientSession | None = None
        self._scheduler_client: SchedulerClient | None = None
        self._runtime_interval = config.METRICS.RUNTIME_REFRESH_SEC
        self._db_interval = config.METRICS.DB_REFRESH_SEC
        self._initialize_feature_flags()

    def _initialize_feature_flags(self) -> None:
        self.cache.set_feature_availability("pipeline_metrics", True)
        self.cache.set_feature_availability("queue_metrics", True)
        self.cache.set_feature_availability("worker_health", True)
        self.cache.set_feature_availability("service_resources", True)
        self.cache.set_feature_availability("product_adoption", True)
        self.cache.set_feature_availability("mttr", True)
        self.cache.set_feature_availability("node_stability", False)
        self.cache.set_feature_availability("schedule_reliability", False)
        self.cache.set_feature_availability("worker_heartbeat_gap", False)
        self.cache.set_feature_availability("worker_stale_total", False)
        self.cache.set_feature_availability("graph_version_dimension", False)

    async def start(self) -> None:
        if self._tasks:
            return

        self._scheduler_session = aiohttp.ClientSession(base_url=config.PROJECT_SCHEDULER.PROJECT_SCHEDULER_URL)
        self._scheduler_client = SchedulerClient(
            scheduler_url=config.PROJECT_SCHEDULER.PROJECT_SCHEDULER_URL,
            session=self._scheduler_session,
        )
        try:
            await self._run_runtime_refresh()
        except Exception:
            logger.exception("Initial runtime metrics refresh failed")
        try:
            await self._run_db_refresh()
        except Exception:
            logger.exception("Initial DB metrics refresh failed")
        self._tasks = [
            asyncio.create_task(self._periodic_loop("runtime", self._runtime_interval, self._run_runtime_refresh)),
            asyncio.create_task(self._periodic_loop("db", self._db_interval, self._run_db_refresh)),
        ]

    async def stop(self) -> None:
        self._stop_event.set()
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._tasks.clear()
        if self._scheduler_client is not None:
            await self._scheduler_client.close()
            self._scheduler_client = None
        if self._scheduler_session is not None and not self._scheduler_session.closed:
            await self._scheduler_session.close()
            self._scheduler_session = None

    async def _periodic_loop(
        self,
        name: str,
        interval: int,
        refresh_fn: Callable[[], Awaitable[None]],
    ) -> None:
        while not self._stop_event.is_set():
            started_at = time.perf_counter()
            try:
                await refresh_fn()
            except Exception:
                logger.exception("Metrics refresh loop failed", collector=name)
            elapsed = time.perf_counter() - started_at
            await asyncio.sleep(max(1.0, interval - elapsed))

    async def _run_runtime_refresh(self) -> None:
        async with AsyncSessionLocal() as session:
            orchestrator_client = await shared_orchestrator.get()
            await self._execute_collector("queue", self._runtime_interval, lambda: collect_queue_metrics(session))
            await self._execute_collector(
                "workers",
                self._runtime_interval,
                lambda: collect_worker_metrics(session, orchestrator_client),
            )
            await self._execute_collector(
                "system",
                self._runtime_interval,
                lambda: collect_system_metrics(
                    self._system_info_manager,
                    self._scheduler_client,
                    orchestrator_client,
                ),
            )

    async def _run_db_refresh(self) -> None:
        async with AsyncSessionLocal() as session:
            await self._execute_collector("pipeline", self._db_interval, lambda: collect_pipeline_metrics(session))
            await self._execute_collector("adoption", self._db_interval, lambda: collect_adoption_metrics(session))
            await self._execute_collector("schedule", self._db_interval, collect_schedule_metrics)

    async def _execute_collector(
        self,
        collector_name: str,
        ttl_seconds: int,
        collect_fn: Callable[[], Awaitable[CollectorResult]],
    ) -> None:
        lock = self._collector_locks.setdefault(collector_name, asyncio.Lock())
        if lock.locked():
            logger.warning("Skip concurrent metrics collector run", collector=collector_name)
            return

        async with lock:
            started_at = time.perf_counter()
            try:
                result = await collect_fn()
                self.cache.update_snapshot(
                    collector_name,
                    result.metrics,
                    ttl_seconds=ttl_seconds,
                    rows_processed=result.rows_processed,
                )
            except Exception as exc:
                self.cache.mark_failure(collector_name, str(exc), ttl_seconds=ttl_seconds)
                logger.exception(
                    "Metrics collector failed",
                    collector=collector_name,
                    duration_sec=round(time.perf_counter() - started_at, 4),
                )
