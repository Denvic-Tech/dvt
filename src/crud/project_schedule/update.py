from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from src.enums import RetryBackoff
from src.modules.project.infra.db_models import ProjectScheduleRecord
from src.pipeline.execution_mode import PipelineExecutionMode


async def update_project_schedule(
    session: AsyncSession,
    schedule: ProjectScheduleRecord,
    *,
    cron: str | None = None,
    disabled: bool | None = None,
    scheduled_by_user_id: str | None = None,
    mode: PipelineExecutionMode | None = None,
    force_exec: bool | None = None,
    max_retries: int | None = None,
    retry_delay_seconds: int | None = None,
    retry_backoff: RetryBackoff | None = None,
    retry_max_delay_seconds: int | None = None,
) -> ProjectScheduleRecord:
    if cron is not None:
        schedule.cron = cron

    if disabled is not None:
        schedule.disabled = disabled

    if scheduled_by_user_id is not None:
        schedule.scheduled_by_user_id = scheduled_by_user_id

    if mode is not None:
        schedule.mode = mode

    if force_exec is not None:
        schedule.force_exec = force_exec

    if max_retries is not None:
        schedule.max_retries = max_retries

    if retry_delay_seconds is not None:
        schedule.retry_delay_seconds = retry_delay_seconds

    if retry_backoff is not None:
        schedule.retry_backoff = retry_backoff

    if retry_max_delay_seconds is not None:
        schedule.retry_max_delay_seconds = retry_max_delay_seconds

    schedule.updated_at = datetime.now(tz=UTC)
    session.add(schedule)
    await session.flush()
    await session.refresh(schedule)
    return schedule
