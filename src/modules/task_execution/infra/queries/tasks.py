import contextlib
from dataclasses import dataclass
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src.pipeline.execution_mode import PipelineExecutionMode

from ...domain.types import TaskExecutionStatus, TaskSource, TaskTerminationReason
from ..db_models import TaskRecord


@dataclass(frozen=True, slots=True)
class TaskReadModel:
    task_id: str
    user_id: str
    organization_id: str
    project_id: str
    mode: PipelineExecutionMode
    force_exec: bool
    source: TaskSource
    status: TaskExecutionStatus
    assigned_worker_id: str | None
    queued_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    updated_at: datetime
    message: str | None
    termination_reason: TaskTerminationReason | str | None
    schedule_run_id: str | None
    schedule_attempt: int | None


def to_task_read_model(record: TaskRecord) -> TaskReadModel:
    source = record.source if isinstance(record.source, TaskSource) else TaskSource(record.source)
    reason: TaskTerminationReason | str | None = record.termination_reason
    if reason is not None:
        with contextlib.suppress(ValueError):
            reason = TaskTerminationReason(reason)
    return TaskReadModel(
        task_id=record.task_id,
        user_id=record.user_id,
        organization_id=record.organization_id,
        project_id=record.project_id,
        mode=record.mode,
        force_exec=record.force_exec,
        source=source,
        status=record.status,
        assigned_worker_id=record.assigned_worker_id,
        queued_at=record.queued_at,
        started_at=record.started_at,
        finished_at=record.finished_at,
        updated_at=record.updated_at,
        message=record.message,
        termination_reason=reason,
        schedule_run_id=record.schedule_run_id,
        schedule_attempt=record.schedule_attempt,
    )


async def get_task_by_id(session: AsyncSession, *, task_id: str) -> TaskReadModel | None:
    record = (
        await session.execute(sa.select(TaskRecord).where(TaskRecord.task_id == task_id).limit(1))
    ).scalars().first()
    return to_task_read_model(record) if record is not None else None


async def task_exists(session: AsyncSession, *, task_id: str) -> bool:
    return bool((await session.execute(
        sa.select(sa.exists().where(TaskRecord.task_id == task_id))
    )).scalar_one())


async def get_accessible_task(
    session: AsyncSession,
    *,
    task_id: str,
    project_id: str,
    organization_id: str | None,
    owner_user_id: str | None,
) -> TaskReadModel | None:
    filters: list[sa.ColumnExpressionArgument[bool]] = [
        TaskRecord.task_id == task_id,
        TaskRecord.project_id == project_id,
    ]
    if organization_id is not None:
        filters.append(TaskRecord.organization_id == organization_id)
    if owner_user_id is not None:
        filters.append(TaskRecord.user_id == owner_user_id)
    record = (await session.execute(sa.select(TaskRecord).where(*filters).limit(1))).scalars().first()
    return to_task_read_model(record) if record is not None else None


async def get_accessible_task_by_id(
    session: AsyncSession,
    *,
    task_id: str,
    organization_id: str | None,
    owner_user_id: str | None,
) -> TaskReadModel | None:
    filters: list[sa.ColumnExpressionArgument[bool]] = [TaskRecord.task_id == task_id]
    if organization_id is not None:
        filters.append(TaskRecord.organization_id == organization_id)
    if owner_user_id is not None:
        filters.append(TaskRecord.user_id == owner_user_id)
    record = (await session.execute(sa.select(TaskRecord).where(*filters).limit(1))).scalars().first()
    return to_task_read_model(record) if record is not None else None


async def list_queue_tasks(
    session: AsyncSession,
    *,
    statuses: list[TaskExecutionStatus],
    organization_id: str | None,
    owner_user_id: str | None,
    project_id: str | None = None,
    limit: int = 100,
) -> list[TaskReadModel]:
    filters: list[sa.ColumnExpressionArgument[bool]] = [TaskRecord.status.in_(statuses)]
    if organization_id is not None:
        filters.append(TaskRecord.organization_id == organization_id)
    if owner_user_id is not None:
        filters.append(TaskRecord.user_id == owner_user_id)
    if project_id is not None:
        filters.append(TaskRecord.project_id == project_id)
    records = list((await session.execute(
        sa.select(TaskRecord)
        .where(*filters)
        .order_by(sa.desc(TaskRecord.queued_at))
        .limit(limit)
    )).scalars().all())
    return [to_task_read_model(record) for record in records]
