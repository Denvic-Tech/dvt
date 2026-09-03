from collections.abc import Iterable

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.project.infra.db_models import ProjectRecord, ProjectScheduleRecord


async def get_project_schedules(
    session: AsyncSession,
    *filters: sa.ColumnExpressionArgument[bool],
) -> sa.ScalarResult[ProjectScheduleRecord]:
    stmt = (
        sa.select(ProjectScheduleRecord)
        .where(*filters)
        .order_by(ProjectScheduleRecord.created_at.asc(), ProjectScheduleRecord.id.asc())
    )
    return (await session.execute(stmt)).scalars()


async def get_project_schedules_by(
    session: AsyncSession,
    *,
    schedule_id: str | None = None,
    project_id: str | None = None,
    project_ids: Iterable[str] | None = None,
    organization_id: str | None = None,
    disabled: bool | None = None,
    scheduled_by_user_id: str | None = None,
) -> sa.ScalarResult[ProjectScheduleRecord]:
    filters: list[sa.ColumnExpressionArgument[bool]] = []

    if schedule_id is not None:
        filters.append(ProjectScheduleRecord.id == schedule_id)

    if project_id is not None:
        filters.append(ProjectScheduleRecord.project_id == project_id)

    if project_ids is not None:
        filters.append(ProjectScheduleRecord.project_id.in_(tuple(project_ids)))

    if organization_id is not None:
        filters.append(ProjectRecord.organization_id == organization_id)

    if disabled is not None:
        filters.append(ProjectScheduleRecord.disabled.is_(disabled))

    if scheduled_by_user_id is not None:
        filters.append(ProjectScheduleRecord.scheduled_by_user_id == scheduled_by_user_id)

    stmt = sa.select(ProjectScheduleRecord).join(ProjectRecord, ProjectRecord.id == ProjectScheduleRecord.project_id)
    stmt = stmt.where(*filters).order_by(ProjectScheduleRecord.created_at.asc(), ProjectScheduleRecord.id.asc())
    return (await session.execute(stmt)).scalars()
