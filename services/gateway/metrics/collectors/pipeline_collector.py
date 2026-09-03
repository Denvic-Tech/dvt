from __future__ import annotations

from collections import defaultdict

import sqlalchemy as sa

from src.modules.task_execution.domain.types import TaskExecutionStatus
from src.modules.task_execution.infra.db_models import TaskRecord

from ..cache import MetricRecord
from ..normalizers import normalize_error_category
from .common import WINDOW_TO_DELTA, CollectorResult, utcnow

FINAL_STATUSES = (
    TaskExecutionStatus.SUCCESS,
    TaskExecutionStatus.ERROR,
    TaskExecutionStatus.CANCELLED,
)


def _extract_epoch_seconds(expr) -> sa.ColumnElement[float]:
    return sa.cast(sa.extract("epoch", expr), sa.Float)


def _task_duration_seconds(task: TaskRecord) -> float:
    if task.started_at is not None and task.finished_at is not None:
        return max(0.0, (task.finished_at - task.started_at).total_seconds())
    return 0.0


async def collect_pipeline_metrics(session) -> CollectorResult:
    now = utcnow()
    metrics: list[MetricRecord] = []
    rows_processed = 0

    total_stmt = (
        sa.select(TaskRecord.project_id, TaskRecord.status, sa.func.count())
        .where(TaskRecord.status.in_(FINAL_STATUSES))
        .group_by(TaskRecord.project_id, TaskRecord.status)
    )
    for project_id, status, count in (await session.execute(total_stmt)).all():
        metrics.append(
            MetricRecord(
                name="gateway_pipeline_runs_total",
                documentation="Total finalized pipeline runs by project and status",
                kind="counter",
                labels={"project_id": str(project_id), "status": str(status)},
                value=float(count),
            )
        )
        rows_processed += 1

    for window, delta in WINDOW_TO_DELTA.items():
        cutoff = now - delta
        window_stmt = (
            sa.select(TaskRecord.project_id, TaskRecord.status, sa.func.count())
            .where(TaskRecord.status.in_(FINAL_STATUSES), TaskRecord.finished_at.is_not(None), TaskRecord.finished_at >= cutoff)
            .group_by(TaskRecord.project_id, TaskRecord.status)
        )
        grouped: dict[str, dict[str, int]] = defaultdict(dict)
        for project_id, status, count in (await session.execute(window_stmt)).all():
            grouped[str(project_id)][str(status)] = int(count)

        for project_id, counts in grouped.items():
            denom = sum(counts.values())
            success_rate = counts.get(TaskExecutionStatus.SUCCESS.value, 0) / denom if denom else 0.0
            error_rate = counts.get(TaskExecutionStatus.ERROR.value, 0) / denom if denom else 0.0
            cancel_rate = counts.get(TaskExecutionStatus.CANCELLED.value, 0) / denom if denom else 0.0
            metrics.extend([
                MetricRecord(
                    name="gateway_pipeline_success_rate_cached",
                    documentation="Cached pipeline success rate by project and window",
                    kind="gauge",
                    labels={"project_id": project_id, "window": window},
                    value=success_rate,
                ),
                MetricRecord(
                    name="gateway_pipeline_error_rate_cached",
                    documentation="Cached pipeline error rate by project and window",
                    kind="gauge",
                    labels={"project_id": project_id, "window": window},
                    value=error_rate,
                ),
                MetricRecord(
                    name="gateway_pipeline_cancel_rate_cached",
                    documentation="Cached pipeline cancel rate by project and window",
                    kind="gauge",
                    labels={"project_id": project_id, "window": window},
                    value=cancel_rate,
                ),
            ])
            rows_processed += 1

        queue_wait_stmt = (
            sa.select(
                TaskRecord.project_id,
                sa.func.percentile_cont(0.5).within_group(
                    _extract_epoch_seconds(TaskRecord.started_at - TaskRecord.queued_at)
                ),
                sa.func.percentile_cont(0.95).within_group(
                    _extract_epoch_seconds(TaskRecord.started_at - TaskRecord.queued_at)
                ),
            )
            .where(
                TaskRecord.started_at.is_not(None),
                TaskRecord.queued_at.is_not(None),
                TaskRecord.started_at >= cutoff,
            )
            .group_by(TaskRecord.project_id)
        )
        for project_id, p50, p95 in (await session.execute(queue_wait_stmt)).all():
            metrics.extend([
                MetricRecord(
                    name="gateway_pipeline_queue_wait_seconds_p50",
                    documentation="Cached queue wait p50 in seconds",
                    kind="gauge",
                    labels={"project_id": str(project_id), "window": window},
                    value=float(p50 or 0.0),
                ),
                MetricRecord(
                    name="gateway_pipeline_queue_wait_seconds_p95",
                    documentation="Cached queue wait p95 in seconds",
                    kind="gauge",
                    labels={"project_id": str(project_id), "window": window},
                    value=float(p95 or 0.0),
                ),
            ])
            rows_processed += 1

        execution_stmt = (
            sa.select(
                TaskRecord.project_id,
                sa.func.percentile_cont(0.5).within_group(
                    _extract_epoch_seconds(TaskRecord.finished_at - TaskRecord.started_at)
                ),
                sa.func.percentile_cont(0.95).within_group(
                    _extract_epoch_seconds(TaskRecord.finished_at - TaskRecord.started_at)
                ),
                sa.func.percentile_cont(0.99).within_group(
                    _extract_epoch_seconds(TaskRecord.finished_at - TaskRecord.started_at)
                ),
                sa.func.avg(_extract_epoch_seconds(TaskRecord.finished_at - TaskRecord.started_at)),
                sa.func.count(),
            )
            .where(
                TaskRecord.started_at.is_not(None),
                TaskRecord.finished_at.is_not(None),
                TaskRecord.finished_at >= cutoff,
            )
            .group_by(TaskRecord.project_id)
        )
        for project_id, p50, p95, p99, avg_value, sample_count in (await session.execute(execution_stmt)).all():
            metrics.extend([
                MetricRecord(
                    name="gateway_pipeline_execution_seconds_p50",
                    documentation="Cached pipeline execution time p50 in seconds",
                    kind="gauge",
                    labels={"project_id": str(project_id), "window": window},
                    value=float(p50 or 0.0),
                ),
                MetricRecord(
                    name="gateway_pipeline_execution_seconds_p95",
                    documentation="Cached pipeline execution time p95 in seconds",
                    kind="gauge",
                    labels={"project_id": str(project_id), "window": window},
                    value=float(p95 or 0.0),
                ),
                MetricRecord(
                    name="gateway_pipeline_execution_seconds_p99",
                    documentation="Cached pipeline execution time p99 in seconds",
                    kind="gauge",
                    labels={"project_id": str(project_id), "window": window},
                    value=float(p99 or 0.0),
                ),
                MetricRecord(
                    name="gateway_pipeline_execution_seconds_avg",
                    documentation="Cached pipeline execution time average in seconds",
                    kind="gauge",
                    labels={"project_id": str(project_id), "window": window},
                    value=float(avg_value or 0.0),
                ),
                MetricRecord(
                    name="gateway_pipeline_execution_samples_total",
                    documentation="Execution samples used for cached pipeline latency metrics",
                    kind="gauge",
                    labels={"project_id": str(project_id), "window": window},
                    value=float(sample_count or 0.0),
                ),
            ])
            rows_processed += 1

        mttr_stmt = (
            sa.select(TaskRecord.project_id, TaskRecord.status, TaskRecord.finished_at)
            .where(
                TaskRecord.finished_at.is_not(None),
                TaskRecord.finished_at >= cutoff,
                TaskRecord.status.in_(FINAL_STATUSES),
            )
            .order_by(TaskRecord.project_id, TaskRecord.finished_at)
        )
        mttr_by_project: dict[str, list[float]] = defaultdict(list)
        previous_error: dict[str, object] = {}
        for project_id, status, finished_at in (await session.execute(mttr_stmt)).all():
            project_key = str(project_id)
            if status == TaskExecutionStatus.ERROR:
                previous_error[project_key] = finished_at
                continue
            if status == TaskExecutionStatus.SUCCESS and project_key in previous_error:
                mttr_by_project[project_key].append((finished_at - previous_error[project_key]).total_seconds())
                previous_error.pop(project_key, None)

        for project_id, samples in mttr_by_project.items():
            if not samples:
                continue
            sorted_samples = sorted(samples)
            p50 = sorted_samples[int((len(sorted_samples) - 1) * 0.5)]
            p95 = sorted_samples[int((len(sorted_samples) - 1) * 0.95)]
            metrics.extend([
                MetricRecord(
                    name="gateway_pipeline_mttr_seconds_p50",
                    documentation="Cached MTTR p50 in seconds",
                    kind="gauge",
                    labels={"project_id": project_id, "window": window},
                    value=float(p50),
                ),
                MetricRecord(
                    name="gateway_pipeline_mttr_seconds_p95",
                    documentation="Cached MTTR p95 in seconds",
                    kind="gauge",
                    labels={"project_id": project_id, "window": window},
                    value=float(p95),
                ),
                MetricRecord(
                    name="gateway_pipeline_mttr_incidents_total",
                    documentation="MTTR incident count used in cached calculations",
                    kind="gauge",
                    labels={"project_id": project_id, "window": window},
                    value=float(len(samples)),
                ),
            ])
            rows_processed += 1

    error_stmt = (
        sa.select(TaskRecord.project_id, TaskRecord.message, sa.func.count())
        .where(TaskRecord.status == TaskExecutionStatus.ERROR)
        .group_by(TaskRecord.project_id, TaskRecord.message)
    )
    for project_id, message, count in (await session.execute(error_stmt)).all():
        category = normalize_error_category(message)
        labels = {
            "project_id": str(project_id),
            "node_type": "unknown",
            "graph_version": "unknown",
            "error_category": category,
        }
        metrics.extend([
            MetricRecord(
                name="gateway_pipeline_errors_total",
                documentation="Total pipeline errors by normalized category",
                kind="counter",
                labels=labels,
                value=float(count),
            ),
            MetricRecord(
                name="gateway_pipeline_top_error_reason_total",
                documentation="Top normalized pipeline error reasons",
                kind="counter",
                labels=labels,
                value=float(count),
            ),
        ])
        rows_processed += 1

    cancel_stmt = (
        sa.select(TaskRecord.project_id, sa.func.count())
        .where(TaskRecord.status == TaskExecutionStatus.CANCELLED)
        .group_by(TaskRecord.project_id)
    )
    for project_id, count in (await session.execute(cancel_stmt)).all():
        metrics.append(
            MetricRecord(
                name="gateway_pipeline_cancelled_total",
                documentation="Total cancelled pipeline runs",
                kind="counter",
                labels={"project_id": str(project_id)},
                value=float(count),
            )
        )
        rows_processed += 1

    # Per-task metrics are intentionally limited to a recent window to avoid
    # unbounded metric cardinality growth on the Prometheus side.
    recent_tasks_cutoff = now - WINDOW_TO_DELTA["24h"]
    recent_tasks_stmt = (
        sa.select(TaskRecord)
        .where(TaskRecord.updated_at >= recent_tasks_cutoff)
        .order_by(TaskRecord.updated_at.desc(), TaskRecord.task_id.desc())
    )
    recent_tasks = (await session.execute(recent_tasks_stmt)).scalars().all()
    for task in recent_tasks:
        status_labels = {
            "task_id": str(task.task_id),
            "project_id": str(task.project_id),
            "status": str(task.status),
        }
        metrics.append(
            MetricRecord(
                name="gateway_pipeline_task_status",
                documentation="Status of a recent individual task; value is always 1 for the current task status",
                kind="gauge",
                labels=status_labels,
                value=1.0,
            )
        )
        metrics.append(
            MetricRecord(
                name="gateway_pipeline_task_duration_seconds",
                documentation="Execution duration in seconds for a recent individual task",
                kind="gauge",
                labels=status_labels,
                value=_task_duration_seconds(task),
            )
        )
        rows_processed += 2

    return CollectorResult(metrics=metrics, rows_processed=rows_processed)
