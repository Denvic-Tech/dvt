from __future__ import annotations

from ..cache import MetricRecord
from .common import CollectorResult


async def collect_schedule_metrics() -> CollectorResult:
    return CollectorResult(
        metrics=[
            MetricRecord(
                name="gateway_schedule_metrics_available",
                documentation="Whether schedule reliability metrics are currently backed by persisted source data",
                kind="gauge",
                labels={},
                value=0.0,
            )
        ],
        rows_processed=1,
    )
