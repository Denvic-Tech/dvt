from services.gateway.metrics.cache import MetricsCache, MetricRecord


def test_metrics_cache_keeps_last_success_and_runtime_counters():
    cache = MetricsCache()
    cache.update_snapshot(
        "pipeline",
        [
            MetricRecord(
                name="gateway_pipeline_success_rate_cached",
                documentation="doc",
                kind="gauge",
                labels={"project_id": "p1", "window": "1h"},
                value=0.75,
            )
        ],
        ttl_seconds=60,
        rows_processed=3,
    )
    cache.increment_runtime_counter("gateway_graph_operations_total", {"operation_type": "node_create"}, 2)
    cache.set_feature_availability("node_stability", False)

    snapshots, runtime_metrics = cache.export_state(
        runtime_counter_docs={"gateway_graph_operations_total": "graph ops"}
    )

    assert len(snapshots) == 1
    assert snapshots[0].name == "pipeline"
    assert snapshots[0].success is True
    assert snapshots[0].rows_processed == 3
    assert any(metric.name == "gateway_graph_operations_total" for metric in runtime_metrics)
    assert any(
        metric.name == "gateway_metrics_feature_available"
        and metric.labels["feature"] == "node_stability"
        and metric.value == 0.0
        for metric in runtime_metrics
    )
