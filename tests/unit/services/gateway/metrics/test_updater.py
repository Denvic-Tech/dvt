import pytest

from services.gateway.metrics.cache import MetricsCache, MetricRecord
from services.gateway.metrics.updater import MetricsUpdaterManager
from services.gateway.metrics.collectors.common import CollectorResult


@pytest.mark.asyncio
async def test_updater_execute_collector_updates_cache():
    cache = MetricsCache()
    manager = MetricsUpdaterManager(cache)

    async def _collector():
        return CollectorResult(
            metrics=[
                MetricRecord(
                    name="gateway_queue_length",
                    documentation="doc",
                    kind="gauge",
                    labels={"queue_name": "default"},
                    value=7,
                )
            ],
            rows_processed=1,
        )

    await manager._execute_collector("queue", 15, _collector)
    snapshots, _ = cache.export_state(runtime_counter_docs={})

    assert snapshots[0].name == "queue"
    assert snapshots[0].success is True
    assert snapshots[0].metrics[0].value == 7


@pytest.mark.asyncio
async def test_updater_execute_collector_marks_failure_and_keeps_previous_metrics():
    cache = MetricsCache()
    manager = MetricsUpdaterManager(cache)

    async def _success():
        return CollectorResult(
            metrics=[
                MetricRecord(
                    name="gateway_queue_length",
                    documentation="doc",
                    kind="gauge",
                    labels={"queue_name": "default"},
                    value=4,
                )
            ],
            rows_processed=1,
        )

    async def _failure():
        raise RuntimeError("boom")

    await manager._execute_collector("queue", 15, _success)
    await manager._execute_collector("queue", 15, _failure)
    snapshots, _ = cache.export_state(runtime_counter_docs={})

    assert snapshots[0].success is False
    assert snapshots[0].metrics[0].value == 4
    assert snapshots[0].last_error == "boom"
