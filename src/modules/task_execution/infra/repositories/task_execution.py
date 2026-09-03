from collections.abc import Callable, Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from ...domain.entities import DispatchOutboxItem, EnqueueTaskResult, TaskExecution
from ...domain.policies import choose_termination_reason, terminal_status_for_termination_reason
from ...domain.repositories import DispatchOutbox, TaskExecutionRepository
from ...domain.types import (
    CLAIMABLE_STATUSES,
    ROOT_EXECUTION_SOURCES,
    SUPERSEDABLE_STATUSES,
    TERMINAL_STATUSES,
    WORKER_OWNED_ACTIVE_STATUSES,
    TaskExecutionStatus,
    TaskSource,
    TaskTerminationReason,
)
from ..db_models import TaskDispatchOutboxRecord, TaskRecord


class SQLTaskExecutionRepository(TaskExecutionRepository, DispatchOutbox):
    """SQL adapter over the legacy ``tasks`` table and the dispatch outbox."""

    def __init__(self, session_factory: Callable[[], AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create_pending(self, execution: TaskExecution) -> TaskExecution:
        async with self._session_factory() as session:
            existing = await session.scalar(
                sa.select(TaskRecord).where(TaskRecord.task_id == execution.task_id).limit(1)
            )
            if existing is not None:
                return _to_entity(existing)
            task = TaskRecord(
                task_id=execution.task_id,
                user_id=execution.user_id,
                organization_id=execution.organization_id,
                project_id=execution.project_id,
                mode=execution.mode,
                force_exec=execution.force_exec,
                source=execution.source,
                status=TaskExecutionStatus.PENDING,
                queued_at=execution.queued_at,
                schedule_run_id=execution.schedule_run_id,
                schedule_attempt=execution.schedule_attempt,
            )
            session.add(task)
            await session.commit()
            return _to_entity(task)

    async def enqueue_with_dispatch(
        self,
        execution: TaskExecution,
        payload: dict[str, object],
    ) -> EnqueueTaskResult:
        async with self._session_factory() as session:
            if execution.source in ROOT_EXECUTION_SOURCES:
                bind = session.get_bind()
                if bind.dialect.name == "postgresql":
                    await session.execute(
                        sa.text("SELECT pg_advisory_xact_lock(hashtext(:project_id))"),
                        {"project_id": execution.project_id},
                    )

            task = await session.scalar(
                sa.select(TaskRecord).where(TaskRecord.task_id == execution.task_id).with_for_update()
            )
            if task is None:
                task = TaskRecord(
                    task_id=execution.task_id,
                    user_id=execution.user_id,
                    organization_id=execution.organization_id,
                    project_id=execution.project_id,
                    mode=execution.mode,
                    force_exec=execution.force_exec,
                    source=execution.source,
                    status=TaskExecutionStatus.QUEUED,
                    queued_at=execution.queued_at,
                    schedule_run_id=execution.schedule_run_id,
                    schedule_attempt=execution.schedule_attempt,
                )
                session.add(task)
            elif task.status == TaskExecutionStatus.PENDING:
                task.status = TaskExecutionStatus.QUEUED
                task.updated_at = datetime.now(tz=UTC)
            elif task.status != TaskExecutionStatus.QUEUED:
                await session.commit()
                return EnqueueTaskResult(execution=_to_entity(task))

            superseded: tuple[TaskExecution, ...] = ()
            if execution.source in ROOT_EXECUTION_SOURCES:
                task, superseded = await self._coalesce_root_executions(session, task)
                if task.status == TaskExecutionStatus.CANCELLED:
                    await session.commit()
                    return EnqueueTaskResult(execution=_to_entity(task), superseded=superseded)

            outbox = await session.scalar(
                sa.select(TaskDispatchOutboxRecord).where(
                    TaskDispatchOutboxRecord.task_id == execution.task_id
                )
            )
            if outbox is None:
                session.add(TaskDispatchOutboxRecord(task_id=execution.task_id, payload=payload))
            await session.commit()
            return EnqueueTaskResult(execution=_to_entity(task), superseded=superseded)

    async def _coalesce_root_executions(
        self,
        session: AsyncSession,
        current: TaskRecord,
    ) -> tuple[TaskRecord, tuple[TaskExecution, ...]]:
        """Leave only the persisted freshest runnable root execution for a project."""
        candidates = list((await session.scalars(
            sa.select(TaskRecord)
            .where(
                TaskRecord.project_id == current.project_id,
                TaskRecord.source.in_(tuple(ROOT_EXECUTION_SOURCES)),
                TaskRecord.status.in_(tuple(SUPERSEDABLE_STATUSES)),
            )
            .order_by(TaskRecord.queued_at.desc(), TaskRecord.task_id.desc())
            .with_for_update()
        )).all())
        if not candidates:
            return current, ()

        freshest = candidates[0]
        stale = candidates[1:]
        if not stale:
            return current, ()

        superseded = tuple(_to_entity(task) for task in stale)
        stale_ids = [task.task_id for task in stale]
        now = datetime.now(tz=UTC)
        await session.execute(
            sa.update(TaskRecord)
            .where(TaskRecord.task_id.in_(stale_ids))
            .values(
                status=TaskExecutionStatus.CANCELLED,
                termination_reason=TaskTerminationReason.SUPERSEDED_BY_NEWER_EXECUTION,
                finished_at=now,
                updated_at=now,
            )
        )
        await session.execute(
            sa.update(TaskDispatchOutboxRecord)
            .where(
                TaskDispatchOutboxRecord.task_id.in_(stale_ids),
                TaskDispatchOutboxRecord.published_at.is_(None),
            )
            .values(status="CANCELLED")
        )
        if current.task_id in stale_ids:
            current.status = TaskExecutionStatus.CANCELLED
            current.termination_reason = TaskTerminationReason.SUPERSEDED_BY_NEWER_EXECUTION
            current.finished_at = now
            current.updated_at = now
        return current, superseded

    async def claim(self, *, task_id: str, worker_id: str) -> bool:
        async with self._session_factory() as session:
            now = datetime.now(tz=UTC)
            result = await session.execute(
                sa.update(TaskRecord)
                .where(
                    TaskRecord.task_id == task_id,
                    TaskRecord.status.in_(tuple(CLAIMABLE_STATUSES)),
                )
                .values(
                    status=TaskExecutionStatus.STARTED,
                    assigned_worker_id=worker_id,
                    started_at=now,
                    updated_at=now,
                )
            )
            await session.commit()
            return bool(result.rowcount)

    async def mark_running(self, *, task_id: str, worker_id: str) -> bool:
        async with self._session_factory() as session:
            result = await session.execute(
                sa.update(TaskRecord)
                .where(
                    TaskRecord.task_id == task_id,
                    TaskRecord.status == TaskExecutionStatus.STARTED,
                    TaskRecord.assigned_worker_id == worker_id,
                )
                .values(status=TaskExecutionStatus.RUNNING, updated_at=datetime.now(tz=UTC))
            )
            await session.commit()
            return bool(result.rowcount)

    async def finalize(
        self,
        *,
        task_id: str,
        worker_id: str,
        status: TaskExecutionStatus,
        message: str | None = None,
        termination_reason: TaskTerminationReason | str | None = None,
    ) -> bool:
        if status not in TERMINAL_STATUSES:
            raise ValueError(f"Unsupported terminal status: {status}")
        async with self._session_factory() as session:
            task = await session.scalar(
                sa.select(TaskRecord).where(TaskRecord.task_id == task_id).with_for_update()
            )
            if task is None or task.assigned_worker_id != worker_id:
                return False
            if task.status in (
                    TaskExecutionStatus.SUCCESS,
                    TaskExecutionStatus.ERROR,
                    TaskExecutionStatus.CANCELLED,
            ):
                return False
            if status == TaskExecutionStatus.SUCCESS and task.status not in (
                    TaskExecutionStatus.STARTED,
                    TaskExecutionStatus.RUNNING,
            ):
                return False
            if status != TaskExecutionStatus.SUCCESS and task.status not in (
                    TaskExecutionStatus.STARTED,
                    TaskExecutionStatus.RUNNING,
                    TaskExecutionStatus.CANCEL_REQUESTED,
            ):
                return False

            effective_reason = task.termination_reason
            if termination_reason is not None:
                effective_reason = choose_termination_reason(
                    current=effective_reason,
                    requested=termination_reason,
                    hard=False,
                )
            if effective_reason is not None and status != TaskExecutionStatus.SUCCESS:
                expected_status = terminal_status_for_termination_reason(effective_reason)
                if status != expected_status:
                    return False

            now = datetime.now(tz=UTC)
            task.status = status
            task.finished_at = now
            task.updated_at = now
            if message is not None:
                task.message = message
            if effective_reason is not None:
                task.termination_reason = effective_reason
            await session.commit()
            return True

    async def finalize_reconciled(
        self,
        *,
        task_id: str,
        termination_reason: TaskTerminationReason | None,
        message: str | None = None,
    ) -> TaskExecution | None:
        """Authoritative system finalization used only by reconciliation flows.

        Normal worker completion must continue to use ``finalize`` so ownership
        remains guarded by ``assigned_worker_id``. Reconciliation may finalize an
        already requested termination, or a worker-owned active task as
        ``WORKER_LOST`` when the worker can no longer write its own terminal state.
        """
        async with self._session_factory() as session:
            task = await session.scalar(
                sa.select(TaskRecord).where(TaskRecord.task_id == task_id).with_for_update()
            )
            if task is None or task.status in (
                    TaskExecutionStatus.SUCCESS,
                    TaskExecutionStatus.ERROR,
                    TaskExecutionStatus.CANCELLED,
            ):
                return None

            effective_reason = choose_termination_reason(
                current=task.termination_reason,
                requested=termination_reason,
                hard=False,
            )
            if task.status != TaskExecutionStatus.CANCEL_REQUESTED:
                if not (
                        task.status in (TaskExecutionStatus.STARTED, TaskExecutionStatus.RUNNING)
                        and effective_reason == TaskTerminationReason.WORKER_LOST
                ):
                    return None

            terminal_status = terminal_status_for_termination_reason(effective_reason)
            now = datetime.now(tz=UTC)
            task.status = terminal_status
            task.termination_reason = effective_reason
            task.finished_at = now
            task.updated_at = now
            if message is not None:
                task.message = message
            await session.commit()
            return _to_entity(task)

    async def fail_pending(
        self,
        *,
        task_id: str,
        termination_reason: TaskTerminationReason,
        message: str | None = None,
    ) -> TaskExecution | None:
        """Atomically fail a task that has not yet entered execution transport."""
        async with self._session_factory() as session:
            task = await session.scalar(
                sa.select(TaskRecord).where(TaskRecord.task_id == task_id).with_for_update()
            )
            if task is None:
                return None
            if termination_reason is not None and (
                    task.status == TaskExecutionStatus.ERROR
                    and task.termination_reason == termination_reason
            ):
                return _to_entity(task)
            if task.status != TaskExecutionStatus.PENDING:
                return None

            now = datetime.now(tz=UTC)
            task.status = TaskExecutionStatus.ERROR
            if termination_reason is not None:
                task.termination_reason = termination_reason
            task.finished_at = now
            task.updated_at = now
            if message is not None:
                task.message = message
            await session.commit()
            return _to_entity(task)

    async def get(self, *, task_id: str) -> TaskExecution | None:
        async with self._session_factory() as session:
            task = await session.scalar(sa.select(TaskRecord).where(TaskRecord.task_id == task_id))
            return _to_entity(task) if task is not None else None

    async def list_for_reconciliation(
        self,
        *,
        statuses: Sequence[TaskExecutionStatus],
        limit: int = 1000,
    ) -> Sequence[TaskExecution]:
        if not statuses:
            return ()
        async with self._session_factory() as session:
            records = list((await session.scalars(
                sa.select(TaskRecord)
                .where(TaskRecord.status.in_(tuple(statuses)))
                .order_by(TaskRecord.updated_at, TaskRecord.task_id)
                .limit(limit)
            )).all())
            return tuple(_to_entity(record) for record in records)

    async def request_stop(
        self,
        *,
        task_id: str,
        reason: TaskTerminationReason,
        hard: bool,
    ) -> TaskExecution | None:
        async with self._session_factory() as session:
            task = await session.scalar(
                sa.select(TaskRecord).where(TaskRecord.task_id == task_id).with_for_update()
            )
            if task is None:
                return None
            if task.status in (
                    TaskExecutionStatus.SUCCESS,
                    TaskExecutionStatus.ERROR,
                    TaskExecutionStatus.CANCELLED,
            ):
                return _to_entity(task)

            effective_reason = choose_termination_reason(
                current=task.termination_reason,
                requested=reason,
                hard=hard,
            )
            now = datetime.now(tz=UTC)
            if task.status in (TaskExecutionStatus.PENDING, TaskExecutionStatus.QUEUED):
                task.status = TaskExecutionStatus.CANCELLED
                task.finished_at = now
                task.termination_reason = effective_reason
                await session.execute(
                    sa.update(TaskDispatchOutboxRecord)
                    .where(
                        TaskDispatchOutboxRecord.task_id == task_id,
                        TaskDispatchOutboxRecord.published_at.is_(None),
                    )
                    .values(status="CANCELLED")
                )
            else:
                task.status = TaskExecutionStatus.CANCEL_REQUESTED
                task.termination_reason = effective_reason
            task.updated_at = now
            await session.commit()
            return _to_entity(task)

    async def list_worker_owned_active(self, *, limit: int = 1000) -> Sequence[TaskExecution]:
        async with self._session_factory() as session:
            records = list((await session.scalars(
                sa.select(TaskRecord)
                .where(
                    TaskRecord.status.in_(
                        tuple(WORKER_OWNED_ACTIVE_STATUSES)
                    ),
                    TaskRecord.assigned_worker_id.is_not(None),
                )
                .order_by(TaskRecord.started_at, TaskRecord.task_id)
                .limit(limit)
            )).all())
            return tuple(_to_entity(record) for record in records)

    async def pending_dispatches(self, *, limit: int) -> Sequence[DispatchOutboxItem]:
        async with self._session_factory() as session:
            records = list((await session.scalars(
                sa.select(TaskDispatchOutboxRecord)
                .where(TaskDispatchOutboxRecord.status == "PENDING", TaskDispatchOutboxRecord.published_at.is_(None))
                .order_by(TaskDispatchOutboxRecord.created_at)
                .limit(limit)
            )).all())
            return [_to_dispatch(record) for record in records]

    async def mark_dispatch_published(self, *, dispatch_id: str) -> None:
        async with self._session_factory() as session:
            await session.execute(
                sa.update(TaskDispatchOutboxRecord)
                .where(TaskDispatchOutboxRecord.id == dispatch_id, TaskDispatchOutboxRecord.published_at.is_(None))
                .values(status="PUBLISHED", published_at=datetime.now(tz=UTC), last_error=None)
            )
            await session.commit()

    async def record_dispatch_failure(self, *, dispatch_id: str, error: str) -> None:
        async with self._session_factory() as session:
            await session.execute(
                sa.update(TaskDispatchOutboxRecord)
                .where(TaskDispatchOutboxRecord.id == dispatch_id)
                .values(attempts=TaskDispatchOutboxRecord.attempts + 1, last_error=error[:1000])
            )
            await session.commit()


def _to_entity(task: TaskRecord) -> TaskExecution:
    source = task.source if isinstance(task.source, TaskSource) else TaskSource(task.source)
    termination_reason: TaskTerminationReason | str | None = task.termination_reason
    if termination_reason is not None:
        try:
            termination_reason = TaskTerminationReason(termination_reason)
        except ValueError:
            pass
    return TaskExecution(
        task_id=task.task_id,
        user_id=task.user_id,
        organization_id=task.organization_id,
        project_id=task.project_id,
        mode=task.mode,
        source=source,
        status=task.status,
        force_exec=task.force_exec,
        queued_at=task.queued_at,
        schedule_run_id=task.schedule_run_id,
        schedule_attempt=task.schedule_attempt,
        assigned_worker_id=task.assigned_worker_id,
        termination_reason=termination_reason,
        message=task.message,
        updated_at=task.updated_at,
    )


def _to_dispatch(record: TaskDispatchOutboxRecord) -> DispatchOutboxItem:
    return DispatchOutboxItem(
        dispatch_id=record.id,
        task_id=record.task_id,
        payload=record.payload,
        created_at=record.created_at,
        published_at=record.published_at,
        attempts=record.attempts,
    )
