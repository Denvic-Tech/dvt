from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src.clients.scheduler_client import SchedulerClient
from src.modules.project.infra.db_models import ProjectScheduleRecord
from src.modules.project_transfer.domain.entities import ScheduleSnapshot
from src.modules.project_transfer.domain.gateways import ScheduleGateway
from src.modules.project_transfer.domain.value_objects import TransferActor


def _enum_value(value) -> str:
    return str(getattr(value, "value", value))


class ProjectSchedulerGateway(ScheduleGateway):
    """Reads schedules from the shared table, writes through the Project Scheduler service."""

    def __init__(self, session: AsyncSession, client: SchedulerClient) -> None:
        self._session = session
        self._client = client

    async def read(self, project_id: str) -> ScheduleSnapshot | None:
        record = (
            await self._session.execute(
                sa.select(ProjectScheduleRecord).where(ProjectScheduleRecord.project_id == project_id)
            )
        ).scalars().first()
        if record is None:
            return None
        return ScheduleSnapshot(
            cron=record.cron,
            mode=_enum_value(record.mode),
            force_exec=record.force_exec,
            max_retries=record.max_retries,
            retry_delay_seconds=record.retry_delay_seconds,
            retry_backoff=_enum_value(record.retry_backoff),
            retry_max_delay_seconds=record.retry_max_delay_seconds,
            disabled=record.disabled,
        )

    async def disable(self, project_id: str) -> None:
        await self._client.unschedule_project(project_id)

    async def apply(
        self,
        project_id: str,
        schedule: ScheduleSnapshot,
        *,
        enabled: bool,
        actor: TransferActor,
        replace_existing: bool,  # noqa: ARG002 - the scheduler upserts; the flow decides on conflicts
    ) -> None:
        await self._client.schedule_project(
            {
                "project_id": project_id,
                "cron": schedule.cron,
                "mode": schedule.mode,
                "force_exec": schedule.force_exec,
                "max_retries": schedule.max_retries,
                "retry_delay_seconds": schedule.retry_delay_seconds,
                "retry_backoff": schedule.retry_backoff,
                "retry_max_delay_seconds": schedule.retry_max_delay_seconds,
                "disabled": not enabled,
                "scheduled_by_user_id": actor.user_id,
            }
        )
