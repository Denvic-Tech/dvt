from __future__ import annotations

from statistics import mean

from ..cache import MetricRecord
from .common import CollectorResult


def _service_metrics(service_name: str, info) -> list[MetricRecord]:
    return [
        MetricRecord(
            name="gateway_service_cpu_usage_percent",
            documentation="CPU usage percent by service",
            kind="gauge",
            labels={"service_name": service_name},
            value=float(info.cpu_percent),
        ),
        MetricRecord(
            name="gateway_service_memory_usage_bytes",
            documentation="Memory usage bytes by service",
            kind="gauge",
            labels={"service_name": service_name},
            value=float(info.ram_used),
        ),
        MetricRecord(
            name="gateway_service_disk_usage_bytes",
            documentation="Disk usage bytes by service",
            kind="gauge",
            labels={"service_name": service_name},
            value=float(info.disk_used),
        ),
        MetricRecord(
            name="gateway_service_network_rx_bytes",
            documentation="Network receive bytes by service",
            kind="gauge",
            labels={"service_name": service_name},
            value=float(info.network_bytes_recv),
        ),
        MetricRecord(
            name="gateway_service_network_tx_bytes",
            documentation="Network transmit bytes by service",
            kind="gauge",
            labels={"service_name": service_name},
            value=float(info.network_bytes_sent),
        ),
    ]


async def collect_system_metrics(system_info_manager, scheduler_client, orchestrator_client) -> CollectorResult:
    metrics: list[MetricRecord] = []

    gateway_info = system_info_manager.get_system_info()
    metrics.extend(_service_metrics("gateway", gateway_info))

    if scheduler_client is not None:
        try:
            scheduler_info = await scheduler_client.system_status()
            metrics.extend(_service_metrics("project_scheduler", scheduler_info))
        except Exception:
            pass

    worker_infos = []
    if orchestrator_client is not None:
        try:
            worker_infos = await orchestrator_client.get_system_stats()
        except Exception:
            worker_infos = []

    if worker_infos:
        metrics.extend([
            MetricRecord(
                name="gateway_service_cpu_usage_percent",
                documentation="CPU usage percent by service",
                kind="gauge",
                labels={"service_name": "task_worker_pool"},
                value=float(mean(item.cpu_percent for item in worker_infos)),
            ),
            MetricRecord(
                name="gateway_service_memory_usage_bytes",
                documentation="Memory usage bytes by service",
                kind="gauge",
                labels={"service_name": "task_worker_pool"},
                value=float(sum(item.ram_used for item in worker_infos)),
            ),
            MetricRecord(
                name="gateway_service_disk_usage_bytes",
                documentation="Disk usage bytes by service",
                kind="gauge",
                labels={"service_name": "task_worker_pool"},
                value=float(sum(item.disk_used for item in worker_infos)),
            ),
            MetricRecord(
                name="gateway_service_network_rx_bytes",
                documentation="Network receive bytes by service",
                kind="gauge",
                labels={"service_name": "task_worker_pool"},
                value=float(sum(item.network_bytes_recv for item in worker_infos)),
            ),
            MetricRecord(
                name="gateway_service_network_tx_bytes",
                documentation="Network transmit bytes by service",
                kind="gauge",
                labels={"service_name": "task_worker_pool"},
                value=float(sum(item.network_bytes_sent for item in worker_infos)),
            ),
        ])

    return CollectorResult(metrics=metrics, rows_processed=len(metrics))
