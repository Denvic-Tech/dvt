from .cache import get_metrics_cache


def increment_graph_operation(operation_type: str, amount: float = 1.0) -> None:
    get_metrics_cache().increment_runtime_counter(
        "gateway_graph_operations_total",
        {"operation_type": operation_type},
        amount=amount,
    )


def observe_db_catalog_request(
    *,
    dialect: str,
    operation: str,
    cache_status: str,
    outcome: str,
    duration_seconds: float,
    item_count: int = 0,
    payload_bytes: int = 0,
) -> None:
    labels = {
        "dialect": dialect,
        "operation": operation,
        "cache_status": cache_status,
        "outcome": outcome,
    }
    cache = get_metrics_cache()
    cache.increment_runtime_counter("gateway_db_catalog_requests_total", labels)
    cache.increment_runtime_counter(
        "gateway_db_catalog_request_duration_seconds_total",
        labels,
        amount=duration_seconds,
    )
    cache.increment_runtime_counter(
        "gateway_db_catalog_items_total",
        labels,
        amount=float(item_count),
    )
    cache.increment_runtime_counter(
        "gateway_db_catalog_payload_bytes_total",
        labels,
        amount=float(payload_bytes),
    )
