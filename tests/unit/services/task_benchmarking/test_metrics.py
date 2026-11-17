from services.task_benchmarking import metrics


def test_metrics_store_records_snapshots_and_resets() -> None:
    metrics.reset()
    metrics.record_metric("write", "rows", 10)
    metrics.record_metric("write", "rows", 20)
    metrics.record_metric("read", "mode", "count_rows")

    snapshot = metrics.get_metrics()
    snapshot["write"]["rows"] = -1

    assert metrics.get_metrics() == {"write": {"rows": 20}, "read": {"mode": "count_rows"}}
    metrics.reset()
    assert metrics.get_metrics() == {}
