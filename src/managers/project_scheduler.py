import asyncio
from contextlib import suppress
from datetime import UTC, datetime, timedelta

from apscheduler.events import EVENT_JOB_ERROR, JobExecutionEvent
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.schedulers.base import undefined
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.exc import IntegrityError

from src.crud import (
    project as project_crud,
    project_schedule as project_schedule_crud,
    project_schedule_run as schedule_run_crud,
)
from src.crud.admin import user as user_crud
from src.db import async_engine as engine
from src.db.session import AsyncSession
from src.enums import RetryBackoff
from src.exception_registry import ProjectNotFoundException
from src.infra.task import enqueue_task_from_project
from src.logger import logger
from src.modules.project.domain import ProjectScheduleRunStatus
from src.modules.project.infra.db_models import ProjectScheduleRecord, ProjectScheduleRunRecord
from src.modules.task_execution.domain.types import TaskExecutionStatus, TaskSource
from src.pipeline.execution_mode import PipelineExecutionMode
from src.schemas.internal.project_scheduler import (
    ProjectSchedulePatchRequest,
    ProjectScheduleResponse,
    ProjectScheduleRunChainResponse,
    validate_retry_policy,
)

RECONCILE_INTERVAL_SECONDS = 1.0
START_LEASE_SECONDS = 60
RECONCILE_BATCH_SIZE = 100


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class ProjectSchedulerManager:
    """Планирует cron-запуски и сопровождает устойчивые retry-цепочки."""

    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self.scheduler.add_listener(self.job_error_listener, EVENT_JOB_ERROR)
        self._reconcile_task: asyncio.Task | None = None
        self._reconcile_wakeup = asyncio.Event()

    # -------------------- lifecycle --------------------

    def start(self) -> None:
        self.scheduler.start()
        self._reconcile_task = asyncio.create_task(
            self._reconcile_loop(),
            name="project-schedule-reconciler",
        )
        logger.info("AsyncIOScheduler and project schedule reconciler started")

    async def init_from_project_schedules(self) -> int:
        scheduled_count = 0
        async with AsyncSession(engine) as session:
            schedules = await project_schedule_crud.get_project_schedules_by(
                session=session,
                disabled=False,
            )

            for schedule in schedules:
                cron = (schedule.cron or "").strip()
                if not cron:
                    continue
                try:
                    self._schedule_project_in_memory(
                        project_id=schedule.project_id,
                        cron=cron,
                        next_run_time=None,
                    )
                    scheduled_count += 1
                except Exception as exc:
                    logger.error(
                        f"Failed to restore project schedule project_id={schedule.project_id} "
                        f"cron='{cron}': {exc}"
                    )

        self._reconcile_wakeup.set()
        logger.info(f"ProjectScheduler initialized: scheduled={scheduled_count}")
        return scheduled_count

    async def shutdown(self) -> None:
        if self._reconcile_task is not None:
            self._reconcile_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._reconcile_task
            self._reconcile_task = None
        self.scheduler.shutdown(wait=False)
        logger.info("AsyncIOScheduler and project schedule reconciler stopped")

    # -------------------- listeners --------------------

    @staticmethod
    def job_error_listener(event: JobExecutionEvent) -> None:
        if event.exception:
            logger.error(f"Error in scheduled job ID={event.job_id}: {event.exception}")
            if event.traceback:
                logger.debug(f"Traceback:\n{event.traceback}")

    # -------------------- cron and retry chains --------------------

    async def start_scheduled_run(self, project_id: str) -> None:
        """Create a durable run chain for one cron occurrence."""
        now = _utcnow()
        async with AsyncSession(engine) as session:
            schedule = (
                await project_schedule_crud.get_project_schedules_by(
                    session=session,
                    project_id=project_id,
                    disabled=False,
                )
            ).first()
            if schedule is None:
                logger.warning(
                    f"Skipping cron for missing or disabled schedule project_id={project_id}"
                )
                return

            active_run = await schedule_run_crud.get_active_run(
                session,
                schedule_id=schedule.id,
            )
            if active_run is not None:
                logger.warning(
                    f"Skipping overlapping cron project_id={project_id} active_run_id={active_run.id}"
                )
                return

            try:
                run = await schedule_run_crud.create_project_schedule_run(
                    session,
                    schedule=schedule,
                    scheduled_at=now,
                )
                run_id = run.id
                max_attempts = run.max_retries + 1
                await session.commit()
            except IntegrityError:
                await session.rollback()
                logger.warning(
                    f"Skipping concurrent cron project_id={project_id}: active run exists"
                )
                return

        logger.info(
            f"Created schedule run chain run_id={run_id} project_id={project_id} "
            f"max_attempts={max_attempts}"
        )
        self._reconcile_wakeup.set()

    async def _reconcile_loop(self) -> None:
        while True:
            try:
                await self.reconcile_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Project schedule reconciliation pass failed")

            try:
                await asyncio.wait_for(
                    self._reconcile_wakeup.wait(),
                    timeout=RECONCILE_INTERVAL_SECONDS,
                )
            except TimeoutError:
                pass
            finally:
                self._reconcile_wakeup.clear()

    async def reconcile_once(self) -> int:
        now = _utcnow()
        async with AsyncSession(engine) as session:
            runs = await schedule_run_crud.get_reconcilable_runs(
                session,
                now=now,
                limit=RECONCILE_BATCH_SIZE,
            )
            run_ids = [run.id for run in runs if run.id is not None]

        for run_id in run_ids:
            await self._reconcile_run(run_id)
        return len(run_ids)

    async def _reconcile_run(self, run_id: str) -> None:
        should_start_attempt = False
        attempt_number = 0
        now = _utcnow()

        async with AsyncSession(engine) as session:
            run = await schedule_run_crud.get_run_by_id(
                session,
                run_id=run_id,
                for_update=True,
            )
            if run is None or run.finished_at is not None:
                return

            schedule = (
                await project_schedule_crud.get_project_schedules_by(
                    session=session,
                    schedule_id=run.schedule_id,
                )
            ).first()
            if schedule is None or schedule.disabled:
                schedule_run_crud.finish_run(
                    run,
                    status=ProjectScheduleRunStatus.CANCELLED,
                    now=now,
                    error="Schedule disabled or deleted",
                )
                session.add(run)
                await session.commit()
                return

            if run.status == ProjectScheduleRunStatus.PENDING or (
                run.status == ProjectScheduleRunStatus.WAITING_RETRY
                and run.next_retry_at is not None
                and _as_utc(run.next_retry_at) <= now
            ):
                run.attempt_number += 1
                run.status = ProjectScheduleRunStatus.STARTING
                run.attempt_started_at = now
                run.current_task_id = None
                run.next_retry_at = None
                schedule_run_crud.touch(run)
                attempt_number = run.attempt_number
                session.add(run)
                await session.commit()
                should_start_attempt = True
            elif run.status in (
                ProjectScheduleRunStatus.STARTING,
                ProjectScheduleRunStatus.RUNNING,
            ):
                task = await schedule_run_crud.get_attempt_task(
                    session,
                    run_id=run_id,
                    attempt_number=run.attempt_number,
                )
                if task is None:
                    lease_started_at = run.attempt_started_at or run.updated_at
                    if (now - _as_utc(lease_started_at)).total_seconds() >= START_LEASE_SECONDS:
                        self._record_attempt_failure(
                            run,
                            now=now,
                            error=f"Task start lease expired after {START_LEASE_SECONDS} seconds",
                        )
                        session.add(run)
                        await session.commit()
                    return

                run.current_task_id = task.task_id
                if not self._apply_task_result(run, task=task, now=now):
                    run.status = ProjectScheduleRunStatus.RUNNING
                    schedule_run_crud.touch(run)

                session.add(run)
                await session.commit()

        if should_start_attempt:
            await self._enqueue_attempt(run_id=run_id, attempt_number=attempt_number)

    async def _enqueue_attempt(self, *, run_id: str, attempt_number: int) -> None:
        logger.info(f"Starting schedule attempt run_id={run_id} attempt={attempt_number}")
        try:
            async with AsyncSession(engine) as session:
                run = await schedule_run_crud.get_run_by_id(session, run_id=run_id)
                if (
                    run is None
                    or run.finished_at is not None
                    or run.attempt_number != attempt_number
                ):
                    return

                schedule = (
                    await project_schedule_crud.get_project_schedules_by(
                        session=session,
                        schedule_id=run.schedule_id,
                    )
                ).first()
                if schedule is None or schedule.disabled:
                    return

                user = None
                if run.scheduled_by_user_id is not None:
                    user = (
                        await user_crud.get_users_by(
                            session=session,
                            user_id=run.scheduled_by_user_id,
                            is_active=True,
                            is_verified=True,
                        )
                    ).first()
                if user is None:
                    user = await user_crud.get_default_service_user(session)

                project = (
                    await project_crud.get_projects_by(
                        session=session,
                        project_id=schedule.project_id,
                    )
                ).first()
                if project is None:
                    raise ProjectNotFoundException(schedule.project_id)

                task = await enqueue_task_from_project(
                    project=project,
                    mode=run.mode,
                    force_exec=run.force_exec,
                    user=user,
                    session=session,
                    source=TaskSource.SCHEDULER,
                    schedule_run_id=run_id,
                    schedule_attempt=attempt_number,
                )

            async with AsyncSession(engine) as update_session:
                current_run = await schedule_run_crud.get_run_by_id(
                    update_session,
                    run_id=run_id,
                    for_update=True,
                )
                if (
                    current_run is not None
                    and current_run.finished_at is None
                    and current_run.attempt_number == attempt_number
                ):
                    current_run.current_task_id = task.task_id
                    current_run.status = ProjectScheduleRunStatus.RUNNING
                    schedule_run_crud.touch(current_run)
                    update_session.add(current_run)
                    await update_session.commit()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception(
                f"Failed to start schedule attempt run_id={run_id} attempt={attempt_number}"
            )
            await self._record_attempt_failure_by_id(
                run_id=run_id,
                attempt_number=attempt_number,
                error=str(exc),
            )
        finally:
            self._reconcile_wakeup.set()

    async def _record_attempt_failure_by_id(
        self,
        *,
        run_id: str,
        attempt_number: int,
        error: str,
    ) -> None:
        async with AsyncSession(engine) as session:
            run = await schedule_run_crud.get_run_by_id(
                session,
                run_id=run_id,
                for_update=True,
            )
            if run is None or run.finished_at is not None or run.attempt_number != attempt_number:
                return
            task = await schedule_run_crud.get_attempt_task(
                session,
                run_id=run_id,
                attempt_number=attempt_number,
            )
            if task is not None:
                run.current_task_id = task.task_id
                error = task.message or task.termination_reason or error
            self._record_attempt_failure(run, now=_utcnow(), error=error)
            session.add(run)
            await session.commit()

    def _apply_task_result(self, run: ProjectScheduleRunRecord, *, task, now: datetime) -> bool:
        """Apply terminal execution result while keeping retry policy in Project Scheduler."""
        if task.status == TaskExecutionStatus.SUCCESS:
            schedule_run_crud.finish_run(
                run,
                status=ProjectScheduleRunStatus.SUCCESS,
                now=now,
            )
            logger.info(
                f"Schedule run succeeded run_id={run.id} attempt={run.attempt_number}"
            )
            return True

        if task.status == TaskExecutionStatus.ERROR:
            self._record_attempt_failure(
                run,
                now=now,
                error=task.message or task.termination_reason or "Task execution failed",
            )
            return True

        if task.status == TaskExecutionStatus.CANCELLED:
            schedule_run_crud.finish_run(
                run,
                status=ProjectScheduleRunStatus.CANCELLED,
                now=now,
                error=task.termination_reason or task.message,
            )
            logger.info(
                f"Schedule run cancelled without retry run_id={run.id} "
                f"attempt={run.attempt_number}"
            )
            return True

        return False

    def _record_attempt_failure(
        self,
        run: ProjectScheduleRunRecord,
        *,
        now: datetime,
        error: str,
    ) -> None:
        run.last_error = error
        if run.attempt_number <= run.max_retries:
            delay_seconds = self.calculate_retry_delay_seconds(run, run.attempt_number)
            run.status = ProjectScheduleRunStatus.WAITING_RETRY
            run.next_retry_at = now + timedelta(seconds=delay_seconds)
            run.updated_at = now
            logger.warning(
                f"Schedule attempt failed; retry planned run_id={run.id} "
                f"attempt={run.attempt_number} delay_seconds={delay_seconds} error={error}"
            )
            return

        schedule_run_crud.finish_run(
            run,
            status=ProjectScheduleRunStatus.ERROR,
            now=now,
            error=error,
        )
        logger.error(
            f"Schedule retries exhausted run_id={run.id} attempts={run.attempt_number} error={error}"
        )

    @staticmethod
    def calculate_retry_delay_seconds(
        run: ProjectScheduleRunRecord,
        failed_attempt_number: int,
    ) -> int:
        if run.retry_backoff == RetryBackoff.FIXED:
            return run.retry_delay_seconds
        exponential_delay = run.retry_delay_seconds * (2 ** max(0, failed_attempt_number - 1))
        return min(exponential_delay, run.retry_max_delay_seconds)

    # -------------------- scheduling configuration --------------------

    def _schedule_project_in_memory(
        self,
        *,
        project_id: str,
        cron: str,
        next_run_time: datetime | None,
    ) -> None:
        cron_trigger = CronTrigger.from_crontab(cron, timezone="UTC")
        self.scheduler.add_job(
            self.start_scheduled_run,
            trigger=cron_trigger,
            kwargs={"project_id": project_id},
            id=project_id,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            next_run_time=(next_run_time if next_run_time is not None else undefined),
        )
        logger.info(f"Project ID={project_id} scheduled with cron '{cron}'")

    async def schedule_project(
        self,
        project_id: str,
        cron: str,
        scheduled_by_user_id: str,
        next_run_time: datetime | None = None,
        mode: PipelineExecutionMode = PipelineExecutionMode.FULL,
        force_exec: bool = False,
        max_retries: int = 0,
        retry_delay_seconds: int = 60,
        retry_backoff: RetryBackoff = RetryBackoff.FIXED,
        retry_max_delay_seconds: int = 3600,
    ) -> None:
        CronTrigger.from_crontab(cron, timezone="UTC")
        validate_retry_policy(
            retry_backoff=retry_backoff,
            retry_delay_seconds=retry_delay_seconds,
            retry_max_delay_seconds=retry_max_delay_seconds,
        )

        async with AsyncSession(engine) as session:
            project = (
                await project_crud.get_projects_by(session=session, project_id=project_id)
            ).first()
            if project is None:
                raise ProjectNotFoundException(project_id)

            schedule = (
                await project_schedule_crud.get_project_schedules_by(
                    session=session,
                    project_id=project_id,
                )
            ).first()
            values = {
                "cron": cron,
                "disabled": False,
                "scheduled_by_user_id": scheduled_by_user_id,
                "mode": mode,
                "force_exec": force_exec,
                "max_retries": max_retries,
                "retry_delay_seconds": retry_delay_seconds,
                "retry_backoff": retry_backoff,
                "retry_max_delay_seconds": retry_max_delay_seconds,
            }
            if schedule is None:
                await project_schedule_crud.create_project_schedule(
                    session=session,
                    project_id=project_id,
                    **values,
                )
            else:
                await project_schedule_crud.update_project_schedule(
                    session=session,
                    schedule=schedule,
                    **values,
                )
            await session.commit()

        self._schedule_project_in_memory(
            project_id=project_id,
            cron=cron,
            next_run_time=next_run_time,
        )

    async def patch_project_schedule(
        self,
        project_id: str,
        patch: ProjectSchedulePatchRequest,
    ) -> None:
        async with AsyncSession(engine) as session:
            schedule = (
                await project_schedule_crud.get_project_schedules_by(
                    session=session,
                    project_id=project_id,
                )
            ).first()
            if schedule is None:
                raise project_schedule_crud.ProjectScheduleNotFoundException(project_id)

            current_job = None if schedule.disabled else self.get_job(project_id)
            fields_set = patch.model_fields_set
            cron = patch.cron if "cron" in fields_set and patch.cron is not None else schedule.cron
            disabled = (
                patch.disabled
                if "disabled" in fields_set and patch.disabled is not None
                else schedule.disabled
            )
            mode = patch.mode if "mode" in fields_set and patch.mode is not None else schedule.mode
            force_exec = (
                patch.force_exec
                if "force_exec" in fields_set and patch.force_exec is not None
                else schedule.force_exec
            )
            max_retries = (
                patch.max_retries
                if "max_retries" in fields_set and patch.max_retries is not None
                else schedule.max_retries
            )
            retry_delay_seconds = (
                patch.retry_delay_seconds
                if "retry_delay_seconds" in fields_set and patch.retry_delay_seconds is not None
                else schedule.retry_delay_seconds
            )
            retry_backoff = (
                patch.retry_backoff
                if "retry_backoff" in fields_set and patch.retry_backoff is not None
                else schedule.retry_backoff
            )
            retry_max_delay_seconds = (
                patch.retry_max_delay_seconds
                if "retry_max_delay_seconds" in fields_set
                and patch.retry_max_delay_seconds is not None
                else schedule.retry_max_delay_seconds
            )
            validate_retry_policy(
                retry_backoff=retry_backoff,
                retry_delay_seconds=retry_delay_seconds,
                retry_max_delay_seconds=retry_max_delay_seconds,
            )

            cron_changed = (
                "cron" in fields_set and patch.cron is not None and patch.cron != schedule.cron
            )
            next_run_time = (
                None
                if cron_changed
                else (current_job.next_run_time if current_job is not None else None)
            )
            if not disabled:
                CronTrigger.from_crontab(cron, timezone="UTC")

            update_values = {
                "cron": cron,
                "disabled": disabled,
                "mode": mode,
                "force_exec": force_exec,
                "max_retries": max_retries,
                "retry_delay_seconds": retry_delay_seconds,
                "retry_backoff": retry_backoff,
                "retry_max_delay_seconds": retry_max_delay_seconds,
            }
            if "scheduled_by_user_id" in fields_set and patch.scheduled_by_user_id is not None:
                update_values["scheduled_by_user_id"] = patch.scheduled_by_user_id
            await project_schedule_crud.update_project_schedule(
                session=session,
                schedule=schedule,
                **update_values,
            )
            if disabled:
                await self._cancel_active_run(session, schedule.id, "Schedule disabled")
            await session.commit()

        if disabled:
            if current_job is not None:
                self.scheduler.remove_job(project_id)
            self._reconcile_wakeup.set()
            return

        self._schedule_project_in_memory(
            project_id=project_id,
            cron=cron,
            next_run_time=next_run_time,
        )

    async def unschedule_project(self, project_id: str) -> None:
        job = self.get_job(project_id)
        if job is not None:
            self.scheduler.remove_job(project_id)
            logger.info(f"Project ID={project_id} unscheduled")

        async with AsyncSession(engine) as session:
            schedule = (
                await project_schedule_crud.get_project_schedules_by(
                    session=session,
                    project_id=project_id,
                )
            ).first()
            if schedule is not None:
                await project_schedule_crud.update_project_schedule(
                    session=session,
                    schedule=schedule,
                    disabled=True,
                )
                await self._cancel_active_run(session, schedule.id, "Schedule unscheduled")
                await session.commit()
        self._reconcile_wakeup.set()

    async def delete_project_schedule(self, project_id: str) -> None:
        job = self.get_job(project_id)
        if job is not None:
            self.scheduler.remove_job(project_id)

        async with AsyncSession(engine) as session:
            schedule = (
                await project_schedule_crud.get_project_schedules_by(
                    session=session,
                    project_id=project_id,
                )
            ).first()
            if schedule is None:
                raise project_schedule_crud.ProjectScheduleNotFoundException(project_id)
            await self._cancel_active_run(session, schedule.id, "Schedule deleted")
            await project_schedule_crud.delete_project_schedule(session=session, schedule=schedule)
            await session.commit()
        self._reconcile_wakeup.set()

    async def _cancel_active_run(
        self,
        session: AsyncSession,
        schedule_id: str,
        reason: str,
    ) -> None:
        active_run = await schedule_run_crud.get_active_run(
            session,
            schedule_id=schedule_id,
            for_update=True,
        )
        if active_run is not None:
            schedule_run_crud.finish_run(
                active_run,
                status=ProjectScheduleRunStatus.CANCELLED,
                now=_utcnow(),
                error=reason,
            )
            session.add(active_run)
            logger.info(f"Cancelled schedule run run_id={active_run.id}: {reason}")

    # -------------------- getters --------------------

    def get_jobs(self):
        return self.scheduler.get_jobs()

    def get_job(self, task_id: str):
        return self.scheduler.get_job(task_id)

    async def get_scheduled_projects(
        self,
        organization_id: str | None = None,
    ) -> list[ProjectScheduleResponse]:
        async with AsyncSession(engine) as session:
            schedules = list(
                await project_schedule_crud.get_project_schedules_by(
                    session=session,
                    organization_id=organization_id,
                )
            )
            latest_runs = await schedule_run_crud.get_latest_runs_by_schedule_ids(
                session,
                schedule_ids=[schedule.id for schedule in schedules],
            )
            return [
                self._to_schedule_response(schedule, latest_runs.get(schedule.id))
                for schedule in schedules
            ]

    async def get_scheduled_project(self, project_id: str) -> ProjectScheduleResponse | None:
        async with AsyncSession(engine) as session:
            schedule = (
                await project_schedule_crud.get_project_schedules_by(
                    session=session,
                    project_id=project_id,
                )
            ).first()
            if schedule is None:
                return None
            latest_runs = await schedule_run_crud.get_latest_runs_by_schedule_ids(
                session,
                schedule_ids=[schedule.id],
            )
            return self._to_schedule_response(schedule, latest_runs.get(schedule.id))

    def _to_schedule_response(
        self,
        schedule: ProjectScheduleRecord,
        latest_run: ProjectScheduleRunRecord | None = None,
    ) -> ProjectScheduleResponse:
        job = None if schedule.disabled else self.get_job(schedule.project_id)
        latest_run_chain = None
        if latest_run is not None:
            latest_run_chain = ProjectScheduleRunChainResponse(
                run_id=latest_run.id,
                state=latest_run.status,
                attempt_number=latest_run.attempt_number,
                max_attempts=latest_run.max_retries + 1,
                current_task_id=latest_run.current_task_id,
                next_retry_at=latest_run.next_retry_at,
                last_error=latest_run.last_error,
                started_at=latest_run.created_at,
                finished_at=latest_run.finished_at,
            )
        return ProjectScheduleResponse(
            project_id=schedule.project_id,
            cron=schedule.cron,
            disabled=schedule.disabled,
            scheduled_by_user_id=schedule.scheduled_by_user_id,
            mode=schedule.mode,
            force_exec=schedule.force_exec,
            max_retries=schedule.max_retries,
            retry_delay_seconds=schedule.retry_delay_seconds,
            retry_backoff=schedule.retry_backoff,
            retry_max_delay_seconds=schedule.retry_max_delay_seconds,
            next_run_time=(job.next_run_time if job is not None else None),
            task_id=(schedule.project_id if job is not None else None),
            latest_run_chain=latest_run_chain,
        )


project_scheduler_manager: ProjectSchedulerManager | None = None
