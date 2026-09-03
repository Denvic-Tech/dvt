from __future__ import annotations

from datetime import timedelta

import sqlalchemy as sa

from src.modules.task_execution.domain.types import TaskExecutionStatus
from src.modules.task_execution.infra.db_models import TaskRecord

from ..cache import MetricRecord
from .common import CollectorResult, utcnow

QUEUE_NAME = "default"
ACTIVE_STATUSES = (
    TaskExecutionStatus.QUEUED,
    TaskExecutionStatus.ASSIGNED,
    TaskExecutionStatus.PENDING,
    TaskExecutionStatus.STARTED,
    TaskExecutionStatus.RUNNING,
)


async def collect_queue_metrics(session) -> CollectorResult:
    now = utcnow()
    metrics: list[MetricRecord] = []

    queue_length = await session.scalar(
        sa.select(sa.func.count()).select_from(TaskRecord).where(TaskRecord.status.in_(ACTIVE_STATUSES))
    )
    oldest_pending = await session.scalar(
        sa.select(sa.func.min(TaskRecord.queued_at)).where(TaskRecord.status.in_(ACTIVE_STATUSES))
    )
    incoming_cutoff = now - timedelta(minutes=1)
    incoming_count = await session.scalar(
        sa.select(sa.func.count()).select_from(TaskRecord).where(TaskRecord.queued_at >= incoming_cutoff)
    )
    processing_count = await session.scalar(
        sa.select(sa.func.count()).select_from(TaskRecord).where(TaskRecord.started_at.is_not(None), TaskRecord.started_at >= incoming_cutoff)
    )

    metrics.extend([
        MetricRecord(
            name="gateway_queue_length",
            documentation="Current queue length inferred from task table",
            kind="gauge",
            labels={"queue_name": QUEUE_NAME},
            value=float(queue_length or 0),
        ),
        MetricRecord(
            name="gateway_queue_oldest_pending_age_seconds",
            documentation="Age of the oldest non-final task in queue",
            kind="gauge",
            labels={"queue_name": QUEUE_NAME},
            value=max(0.0, (now - oldest_pending).total_seconds()) if oldest_pending else 0.0,
        ),
        MetricRecord(
            name="gateway_queue_incoming_rate_per_minute",
            documentation="Incoming task rate per minute",
            kind="gauge",
            labels={"queue_name": QUEUE_NAME},
            value=float(incoming_count or 0),
        ),
        MetricRecord(
            name="gateway_queue_processing_rate_per_minute",
            documentation="Task processing start rate per minute",
            kind="gauge",
            labels={"queue_name": QUEUE_NAME},
            value=float(processing_count or 0),
        ),
    ])
    return CollectorResult(metrics=metrics, rows_processed=4)
