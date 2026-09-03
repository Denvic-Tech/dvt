from __future__ import annotations

import time
from collections import defaultdict

from prometheus_client import REGISTRY
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily

from .cache import MetricRecord, MetricsCache

RUNTIME_COUNTER_DOCS = {
    "gateway_graph_operations_total": "Graph operation totals observed by gateway since process start",
    "gateway_db_catalog_requests_total": "DB catalog requests observed by gateway",
    "gateway_db_catalog_request_duration_seconds_total": "Cumulative DB catalog request duration",
    "gateway_db_catalog_items_total": "DB catalog items returned by gateway",
    "gateway_db_catalog_payload_bytes_total": "Approximate DB catalog payload bytes returned by gateway",
}


class GatewayMetricsCollector:
    def __init__(self, cache: MetricsCache) -> None:
        self._cache = cache

    def collect(self):
        snapshots, runtime_metrics = self._cache.export_state(runtime_counter_docs=RUNTIME_COUNTER_DOCS)
        grouped: dict[tuple[str, str, str, tuple[str, ...]], list[MetricRecord]] = defaultdict(list)

        for snapshot in snapshots:
            yield from self._freshness_metrics(snapshot.name, snapshot)
            for metric in snapshot.metrics:
                key = (
                    metric.name,
                    metric.documentation,
                    metric.kind,
                    tuple(metric.labels.keys()),
                )
                grouped[key].append(metric)

        for metric in runtime_metrics:
            key = (
                metric.name,
                metric.documentation,
                metric.kind,
                tuple(metric.labels.keys()),
            )
            grouped[key].append(metric)

        for (name, documentation, kind, label_names), items in grouped.items():
            family = (
                CounterMetricFamily(name, documentation, labels=list(label_names))
                if kind == "counter"
                else GaugeMetricFamily(name, documentation, labels=list(label_names))
            )
            for item in items:
                family.add_metric(
                    labels=[item.labels[label] for label in label_names],
                    value=item.value,
                )
            yield family

    @staticmethod
    def _freshness_metrics(collector: str, snapshot) -> list[GaugeMetricFamily]:
        last_update = snapshot.updated_at.timestamp() if snapshot.updated_at else 0.0
        age_seconds = max(0.0, time.time() - last_update) if snapshot.updated_at else float(snapshot.ttl_seconds or 0.0)

        last_update_family = GaugeMetricFamily(
            "gateway_metrics_cache_last_update_unixtime",
            "Last successful or attempted metrics cache update time",
            labels=["collector"],
        )
        last_update_family.add_metric([collector], last_update)

        age_family = GaugeMetricFamily(
            "gateway_metrics_cache_age_seconds",
            "Age of cached metrics for a collector",
            labels=["collector"],
        )
        age_family.add_metric([collector], age_seconds)

        success_family = GaugeMetricFamily(
            "gateway_metrics_cache_update_success",
            "Whether the last collector update succeeded",
            labels=["collector"],
        )
        success_family.add_metric([collector], 1.0 if snapshot.success else 0.0)

        entries_family = GaugeMetricFamily(
            "gateway_metrics_cache_entries",
            "Number of exported metric entries in a collector snapshot",
            labels=["collector"],
        )
        entries_family.add_metric([collector], float(len(snapshot.metrics)))

        return [last_update_family, age_family, success_family, entries_family]


_registered_collector: GatewayMetricsCollector | None = None


def install_metrics_exporter(cache: MetricsCache) -> GatewayMetricsCollector:
    global _registered_collector

    if _registered_collector is not None:
        try:
            REGISTRY.unregister(_registered_collector)
        except KeyError:
            pass

    _registered_collector = GatewayMetricsCollector(cache)
    REGISTRY.register(_registered_collector)
    return _registered_collector
