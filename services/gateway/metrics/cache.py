from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import RLock
from typing import Literal

MetricKind = Literal["gauge", "counter"]


@dataclass(frozen=True)
class MetricRecord:
    name: str
    documentation: str
    kind: MetricKind
    labels: dict[str, str]
    value: float


@dataclass
class CollectorSnapshot:
    name: str
    metrics: list[MetricRecord] = field(default_factory=list)
    updated_at: datetime | None = None
    success: bool = False
    last_error: str | None = None
    ttl_seconds: float = 0.0
    rows_processed: int = 0


class MetricsCache:
    def __init__(self) -> None:
        self._lock = RLock()
        self._snapshots: dict[str, CollectorSnapshot] = {}
        self._runtime_counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
        self._feature_availability: dict[str, bool] = {}

    def update_snapshot(
        self,
        collector: str,
        metrics: list[MetricRecord],
        *,
        ttl_seconds: float,
        rows_processed: int = 0,
    ) -> None:
        with self._lock:
            snapshot = self._snapshots.setdefault(collector, CollectorSnapshot(name=collector))
            snapshot.metrics = list(metrics)
            snapshot.updated_at = datetime.now(UTC)
            snapshot.success = True
            snapshot.last_error = None
            snapshot.ttl_seconds = ttl_seconds
            snapshot.rows_processed = rows_processed

    def mark_failure(self, collector: str, error: str, *, ttl_seconds: float) -> None:
        with self._lock:
            snapshot = self._snapshots.setdefault(collector, CollectorSnapshot(name=collector))
            snapshot.success = False
            snapshot.last_error = error
            snapshot.ttl_seconds = ttl_seconds

    def increment_runtime_counter(
        self,
        metric_name: str,
        labels: dict[str, str],
        amount: float = 1.0,
    ) -> None:
        key = (metric_name, tuple(sorted(labels.items())))
        with self._lock:
            self._runtime_counters[key] = self._runtime_counters.get(key, 0.0) + amount

    def set_feature_availability(self, feature: str, available: bool) -> None:
        with self._lock:
            self._feature_availability[feature] = available

    def export_state(
        self,
        *,
        runtime_counter_docs: dict[str, str],
    ) -> tuple[list[CollectorSnapshot], list[MetricRecord]]:
        with self._lock:
            snapshots = [
                CollectorSnapshot(
                    name=snapshot.name,
                    metrics=list(snapshot.metrics),
                    updated_at=snapshot.updated_at,
                    success=snapshot.success,
                    last_error=snapshot.last_error,
                    ttl_seconds=snapshot.ttl_seconds,
                    rows_processed=snapshot.rows_processed,
                )
                for snapshot in self._snapshots.values()
            ]
            runtime_metrics = [
                MetricRecord(
                    name=name,
                    documentation=runtime_counter_docs.get(name, name),
                    kind="counter",
                    labels=dict(label_items),
                    value=value,
                )
                for (name, label_items), value in self._runtime_counters.items()
            ]
            runtime_metrics.extend(
                MetricRecord(
                    name="gateway_metrics_feature_available",
                    documentation="Feature/source availability for gateway metrics",
                    kind="gauge",
                    labels={"feature": feature},
                    value=1.0 if available else 0.0,
                )
                for feature, available in sorted(self._feature_availability.items())
            )
            return snapshots, runtime_metrics


_metrics_cache: MetricsCache | None = None


def get_metrics_cache() -> MetricsCache:
    global _metrics_cache
    if _metrics_cache is None:
        _metrics_cache = MetricsCache()
    return _metrics_cache
