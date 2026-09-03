from sqlalchemy.ext.asyncio import AsyncSession

from src.enums import RetryBackoff
from src.modules.project.infra.db_models import ProjectScheduleRecord
from src.pipeline.execution_mode import PipelineExecutionMode


async def create_project_schedule(
    session: AsyncSession,
    *,
    project_id: str,
    cron: str,
    disabled: bool = False,
    scheduled_by_user_id: str | None = None,
    mode: PipelineExecutionMode = PipelineExecutionMode.FULL,
    force_exec: bool = False,
    max_retries: int = 0,
    retry_delay_seconds: int = 60,
    retry_backoff: RetryBackoff = RetryBackoff.FIXED,
    retry_max_delay_seconds: int = 3600,
) -> ProjectScheduleRecord:
    schedule = ProjectScheduleRecord(
        project_id=project_id,
        cron=cron,
        disabled=disabled,
        scheduled_by_user_id=scheduled_by_user_id,
        mode=mode,
        force_exec=force_exec,
        max_retries=max_retries,
        retry_delay_seconds=retry_delay_seconds,
        retry_backoff=retry_backoff,
        retry_max_delay_seconds=retry_max_delay_seconds,
    )
    session.add(schedule)
    await session.flush()
    await session.refresh(schedule)
    return schedule
