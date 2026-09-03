import sqlalchemy as sa

from src.enums import WorkerStatus
from src.modules.task_execution.domain.types import TaskExecutionStatus
from src.modules.task_execution.infra.db_models import TaskRecord

from ..cache import MetricRecord
from .common import CollectorResult

POOL_NAME = "default"


async def collect_worker_metrics(session, orchestrator_client) -> CollectorResult:
    worker_infos = []
    if orchestrator_client is not None:
        worker_infos = await orchestrator_client.get_system_stats()

    workers_alive = sum(1 for worker in worker_infos if worker.status == WorkerStatus.ONLINE)
    active_tasks = await session.scalar(
        sa.select(sa.func.count()).select_from(TaskRecord).where(
            TaskRecord.status.in_((TaskExecutionStatus.ASSIGNED, TaskExecutionStatus.STARTED, TaskExecutionStatus.RUNNING))
        )
    )
    busy_ratio = min(float(active_tasks or 0) / max(workers_alive, 1), 1.0) if workers_alive else 0.0

    metrics = [
        MetricRecord(
            name="gateway_workers_alive",
            documentation="Alive workers visible to gateway via orchestrator system stats",
            kind="gauge",
            labels={"pool": POOL_NAME},
            value=float(workers_alive),
        ),
        MetricRecord(
            name="gateway_workers_busy_ratio",
            documentation="Approximate busy ratio based on active tasks and alive workers",
            kind="gauge",
            labels={"pool": POOL_NAME},
            value=busy_ratio,
        ),
    ]
    return CollectorResult(metrics=metrics, rows_processed=len(metrics))
