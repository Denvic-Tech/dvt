from __future__ import annotations

import sqlalchemy as sa

from src.modules.pipeline_graph.infra.db_models import GraphNodeRecord
from src.modules.project.infra.db_models import ProjectRecord
from src.modules.task_execution.infra.db_models import TaskRecord

from ..cache import MetricRecord
from .common import WINDOW_TO_DELTA, CollectorResult, utcnow


async def collect_adoption_metrics(session) -> CollectorResult:
    now = utcnow()
    metrics: list[MetricRecord] = []
    rows_processed = 0

    projects_total = await session.scalar(
        sa.select(sa.func.count()).select_from(ProjectRecord)
    )
    metrics.append(
        MetricRecord(
            name="gateway_projects_created_total",
            documentation="Total non-deleted projects",
            kind="counter",
            labels={},
            value=float(projects_total or 0),
        )
    )

    for window, delta in WINDOW_TO_DELTA.items():
        cutoff = now - delta
        active_users = await session.scalar(
            sa.select(sa.func.count(sa.distinct(TaskRecord.user_id))).where(TaskRecord.queued_at >= cutoff)
        )
        metrics.append(
            MetricRecord(
                name="gateway_active_users_total",
                documentation="Active users derived from task runs in a time window",
                kind="gauge",
                labels={"window": window},
                value=float(active_users or 0),
            )
        )

        runs_per_user_subquery = (
            sa.select(TaskRecord.user_id, sa.func.count().label("user_runs"))
            .where(TaskRecord.queued_at >= cutoff)
            .group_by(TaskRecord.user_id)
            .subquery()
        )
        runs_per_user_stmt = sa.select(
            sa.func.percentile_cont(0.5).within_group(runs_per_user_subquery.c.user_runs),
            sa.func.percentile_cont(0.95).within_group(runs_per_user_subquery.c.user_runs),
        )
        p50, p95 = (await session.execute(runs_per_user_stmt)).one()
        metrics.extend([
            MetricRecord(
                name="gateway_runs_per_active_user_p50",
                documentation="p50 of runs per active user in a window",
                kind="gauge",
                labels={"window": window},
                value=float(p50 or 0.0),
            ),
            MetricRecord(
                name="gateway_runs_per_active_user_p95",
                documentation="p95 of runs per active user in a window",
                kind="gauge",
                labels={"window": window},
                value=float(p95 or 0.0),
            ),
        ])

        node_usage_stmt = (
            sa.select(GraphNodeRecord.name, sa.func.count())
            .where(GraphNodeRecord.created_at >= cutoff)
            .group_by(GraphNodeRecord.name)
        )
        for node_type, count in (await session.execute(node_usage_stmt)).all():
            metrics.append(
                MetricRecord(
                    name="gateway_node_type_usage_total",
                    documentation="Node type usage based on created graph nodes in a window",
                    kind="gauge",
                    labels={"node_type": str(node_type), "window": window},
                    value=float(count),
                )
            )
            rows_processed += 1

    return CollectorResult(metrics=metrics, rows_processed=rows_processed + len(metrics))
