from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.project.infra.db_models import ProjectScheduleRecord


async def delete_project_schedule(
    session: AsyncSession,
    schedule: ProjectScheduleRecord,
) -> ProjectScheduleRecord:
    await session.delete(schedule)
    await session.flush()
    return schedule
