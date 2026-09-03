from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from services.gateway.metrics.cache import MetricRecord


WINDOW_TO_DELTA = {
    "1h": timedelta(hours=1),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
}


@dataclass
class CollectorResult:
    metrics: list[MetricRecord]
    rows_processed: int = 0


def utcnow() -> datetime:
    return datetime.now(UTC)
