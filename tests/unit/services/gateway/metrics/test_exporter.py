from services.gateway.metrics.cache import MetricsCache, MetricRecord
from services.gateway.metrics.exporter import GatewayMetricsCollector
from services.gateway.metrics.runtime import increment_graph_operation


def test_exporter_emits_cached_and_runtime_metrics():
    cache = MetricsCache()
    cache.update_snapshot(
        "queue",
        [
            MetricRecord(
                name="gateway_queue_length",
                documentation="Queue length",
                kind="gauge",
                labels={"queue_name": "default"},
                value=5,
            )
        ],
        ttl_seconds=15,
        rows_processed=1,
    )

    collector = GatewayMetricsCollector(cache)
    metric_names = {metric.name for metric in collector.collect()}

    assert "gateway_queue_length" in metric_names
    assert "gateway_metrics_cache_last_update_unixtime" in metric_names
    assert "gateway_metrics_cache_update_success" in metric_names


def test_runtime_graph_operation_counter_uses_shared_cache(monkeypatch):
    cache = MetricsCache()
    monkeypatch.setattr("services.gateway.metrics.cache._metrics_cache", cache)

    increment_graph_operation("edge_create", 3)
    collector = GatewayMetricsCollector(cache)
    families = list(collector.collect())

    assert any(metric.name == "gateway_graph_operations" for metric in families)
