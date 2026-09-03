from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.project.domain import ProjectScheduleRunStatus
from src.modules.project.infra.db_models import ProjectScheduleRecord, ProjectScheduleRunRecord
from src.modules.task_execution.infra.db_models import TaskRecord

ACTIVE_RUN_STATUSES = (
    ProjectScheduleRunStatus.PENDING,
    ProjectScheduleRunStatus.STARTING,
    ProjectScheduleRunStatus.RUNNING,
    ProjectScheduleRunStatus.WAITING_RETRY,
)


async def create_project_schedule_run(
    session: AsyncSession,
    *,
    schedule: ProjectScheduleRecord,
    scheduled_at: datetime,
) -> ProjectScheduleRunRecord:
    run = ProjectScheduleRunRecord(
        schedule_id=schedule.id,
        status=ProjectScheduleRunStatus.PENDING,
        scheduled_at=scheduled_at,
        max_retries=schedule.max_retries,
        retry_delay_seconds=schedule.retry_delay_seconds,
        retry_backoff=schedule.retry_backoff,
        retry_max_delay_seconds=schedule.retry_max_delay_seconds,
        mode=schedule.mode,
        force_exec=schedule.force_exec,
        scheduled_by_user_id=schedule.scheduled_by_user_id,
    )
    session.add(run)
    await session.flush()
    return run


async def get_active_run(
    session: AsyncSession,
    *,
    schedule_id: str,
    for_update: bool = False,
) -> ProjectScheduleRunRecord | None:
    stmt = (
        sa.select(ProjectScheduleRunRecord)
        .where(
            ProjectScheduleRunRecord.schedule_id == schedule_id,
            ProjectScheduleRunRecord.finished_at.is_(None),
        )
        .order_by(ProjectScheduleRunRecord.created_at.desc())
        .limit(1)
    )
    if for_update:
        stmt = stmt.with_for_update(skip_locked=True)
    return (await session.execute(stmt)).scalars().first()


async def get_run_by_id(
    session: AsyncSession,
    *,
    run_id: str,
    for_update: bool = False,
) -> ProjectScheduleRunRecord | None:
    stmt = sa.select(ProjectScheduleRunRecord).where(ProjectScheduleRunRecord.id == run_id)
    if for_update:
        stmt = stmt.with_for_update(skip_locked=True)
    return (await session.execute(stmt)).scalars().first()


async def get_latest_runs_by_schedule_ids(
    session: AsyncSession,
    *,
    schedule_ids: Sequence[str],
) -> dict[str, ProjectScheduleRunRecord]:
    if not schedule_ids:
        return {}

    row_number = (
        sa.func.row_number()
        .over(
            partition_by=ProjectScheduleRunRecord.schedule_id,
            order_by=(
                ProjectScheduleRunRecord.created_at.desc(),
                ProjectScheduleRunRecord.id.desc(),
            ),
        )
        .label("run_rank")
    )
    ranked = (
        sa.select(ProjectScheduleRunRecord.id.label("id"), row_number)
        .where(ProjectScheduleRunRecord.schedule_id.in_(schedule_ids))
        .subquery()
    )
    stmt = (
        sa.select(ProjectScheduleRunRecord)
        .join(ranked, ranked.c.id == ProjectScheduleRunRecord.id)
        .where(ranked.c.run_rank == 1)
    )
    runs = (await session.execute(stmt)).scalars().all()
    return {run.schedule_id: run for run in runs}


async def get_reconcilable_runs(
    session: AsyncSession,
    *,
    now: datetime,
    limit: int = 100,
) -> list[ProjectScheduleRunRecord]:
    stmt = (
        sa.select(ProjectScheduleRunRecord)
        .where(
            ProjectScheduleRunRecord.finished_at.is_(None),
            ProjectScheduleRunRecord.status.in_(ACTIVE_RUN_STATUSES),
            sa.or_(
                ProjectScheduleRunRecord.status.in_(
                    (
                        ProjectScheduleRunStatus.PENDING,
                        ProjectScheduleRunStatus.STARTING,
                        ProjectScheduleRunStatus.RUNNING,
                    )
                ),
                sa.and_(
                    ProjectScheduleRunRecord.status == ProjectScheduleRunStatus.WAITING_RETRY,
                    ProjectScheduleRunRecord.next_retry_at.is_not(None),
                    ProjectScheduleRunRecord.next_retry_at <= now,
                ),
            ),
        )
        .order_by(ProjectScheduleRunRecord.updated_at.asc())
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())


async def get_attempt_task(
    session: AsyncSession,
    *,
    run_id: str,
    attempt_number: int,
) -> TaskRecord | None:
    stmt = sa.select(TaskRecord).where(
        TaskRecord.schedule_run_id == run_id,
        TaskRecord.schedule_attempt == attempt_number,
    )
    return (await session.execute(stmt)).scalars().first()


def touch(run: ProjectScheduleRunRecord) -> None:
    run.updated_at = datetime.now(tz=UTC)


def finish_run(
    run: ProjectScheduleRunRecord,
    *,
    status: ProjectScheduleRunStatus,
    now: datetime,
    error: str | None = None,
) -> None:
    run.status = status
    run.finished_at = now
    run.next_retry_at = None
    run.last_error = error
    run.updated_at = now
