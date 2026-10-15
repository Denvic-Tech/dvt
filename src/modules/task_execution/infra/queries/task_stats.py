"""Read-side aggregations over pipeline executions for dashboard widgets."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import ceil

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src.pipeline.execution_mode import PipelineExecutionMode

from ...domain.types import (
    ROOT_EXECUTION_SOURCES,
    TERMINAL_STATUSES,
    TaskExecutionStatus,
    TaskTerminationReason,
)
from ..db_models import TaskRecord


@dataclass(frozen=True, slots=True)
class RunsBucket:
    start: datetime
    total: int
    success: int
    error: int
    cancelled: int
    running: int


@dataclass(frozen=True, slots=True)
class RunsWindowStats:
    window_start: datetime
    window_end: datetime
    bucket_minutes: int
    total: int
    success: int
    error: int
    cancelled: int
    running: int
    buckets: tuple[RunsBucket, ...]


@dataclass(frozen=True, slots=True)
class ProjectErrorStats:
    project_id: str
    error_count: int
    total_count: int
    last_error_at: datetime


def _ensure_utc(value: datetime) -> datetime:
    """SQLite returns naive datetimes; treat them as UTC."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _root_run_filters() -> list[sa.ColumnExpressionArgument[bool]]:
    """Filters that define a user-visible pipeline run.

    Full-mode root executions only: nested NODE children would multiply the parent run,
    metadata-only runs are schema probes, and superseded queued runs never executed.
    """
    return [
        TaskRecord.mode == PipelineExecutionMode.FULL,
        TaskRecord.source.in_(sorted(source.value for source in ROOT_EXECUTION_SOURCES)),
        sa.or_(
            TaskRecord.termination_reason.is_(None),
            TaskRecord.termination_reason
            != TaskTerminationReason.SUPERSEDED_BY_NEWER_EXECUTION.value,
        ),
    ]


def _scope_filters(
    organization_id: str | None,
    owner_user_id: str | None,
) -> list[sa.ColumnExpressionArgument[bool]]:
    filters: list[sa.ColumnExpressionArgument[bool]] = []
    if organization_id is not None:
        filters.append(TaskRecord.organization_id == organization_id)
    if owner_user_id is not None:
        filters.append(TaskRecord.user_id == owner_user_id)
    return filters


def compute_hourly_window(now: datetime, *, hours: int = 24) -> tuple[datetime, datetime]:
    """Hour-aligned window ending at ``now``: ``hours`` buckets, the last one partial."""
    window_start = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=hours - 1)
    return window_start, now


def aggregate_runs(
    rows: Iterable[tuple[datetime, TaskExecutionStatus | str]],
    *,
    window_start: datetime,
    window_end: datetime,
    bucket: timedelta = timedelta(hours=1),
) -> RunsWindowStats:
    """Bucket ``(queued_at, status)`` rows into fixed-size time buckets."""
    bucket_count = max(1, ceil((window_end - window_start) / bucket))
    # per bucket: success, error, cancelled, running
    counts = [[0, 0, 0, 0] for _ in range(bucket_count)]

    for queued_at, status in rows:
        index = int((_ensure_utc(queued_at) - window_start) // bucket)
        if index < 0:
            continue
        index = min(index, bucket_count - 1)

        status_value = TaskExecutionStatus(status)
        if status_value is TaskExecutionStatus.SUCCESS:
            counts[index][0] += 1
        elif status_value is TaskExecutionStatus.ERROR:
            counts[index][1] += 1
        elif status_value is TaskExecutionStatus.CANCELLED:
            counts[index][2] += 1
        else:
            counts[index][3] += 1

    buckets = tuple(
        RunsBucket(
            start=window_start + bucket * index,
            total=sum(bucket_counts),
            success=bucket_counts[0],
            error=bucket_counts[1],
            cancelled=bucket_counts[2],
            running=bucket_counts[3],
        )
        for index, bucket_counts in enumerate(counts)
    )
    return RunsWindowStats(
        window_start=window_start,
        window_end=window_end,
        bucket_minutes=int(bucket.total_seconds() // 60),
        total=sum(item.total for item in buckets),
        success=sum(item.success for item in buckets),
        error=sum(item.error for item in buckets),
        cancelled=sum(item.cancelled for item in buckets),
        running=sum(item.running for item in buckets),
        buckets=buckets,
    )


async def get_runs_window_stats(
    session: AsyncSession,
    *,
    window_start: datetime,
    window_end: datetime,
    organization_id: str | None,
    owner_user_id: str | None,
) -> RunsWindowStats:
    """Run counts per hour inside ``[window_start, window_end]`` for the access scope."""
    stmt = sa.select(TaskRecord.queued_at, TaskRecord.status).where(
        *_root_run_filters(),
        *_scope_filters(organization_id, owner_user_id),
        TaskRecord.queued_at >= window_start,
        TaskRecord.queued_at <= window_end,
    )
    rows: Sequence[sa.Row] = (await session.execute(stmt)).all()
    return aggregate_runs(
        ((row[0], row[1]) for row in rows),
        window_start=window_start,
        window_end=window_end,
    )


async def get_project_error_stats(
    session: AsyncSession,
    *,
    since: datetime,
    organization_id: str | None,
    owner_user_id: str | None,
    limit: int,
) -> list[ProjectErrorStats]:
    """Projects with the most failed runs since ``since``, most failures first."""
    is_error = TaskRecord.status == TaskExecutionStatus.ERROR
    error_count = sa.func.sum(sa.case((is_error, 1), else_=0)).label("error_count")
    total_count = sa.func.count().label("total_count")
    last_error_at = sa.func.max(sa.case((is_error, TaskRecord.queued_at))).label("last_error_at")

    stmt = (
        sa.select(TaskRecord.project_id, error_count, total_count, last_error_at)
        .where(
            *_root_run_filters(),
            *_scope_filters(organization_id, owner_user_id),
            TaskRecord.queued_at >= since,
            TaskRecord.status.in_(list(TERMINAL_STATUSES)),
        )
        .group_by(TaskRecord.project_id)
        .having(error_count > 0)
        .order_by(sa.desc(error_count), sa.desc(last_error_at), TaskRecord.project_id)
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    return [
        ProjectErrorStats(
            project_id=row[0],
            error_count=int(row[1]),
            total_count=int(row[2]),
            last_error_at=_ensure_utc(row[3]),
        )
        for row in rows
    ]
