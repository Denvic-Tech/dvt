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


def _build_project_schedules_stmt(
    *columns: sa.ColumnExpressionArgument,
    schedule_id: str | None = None,
    project_id: str | None = None,
    project_ids: Iterable[str] | None = None,
    organization_id: str | None = None,
    disabled: bool | None = None,
    scheduled_by_user_id: str | None = None,
) -> sa.Select:
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

    stmt = sa.select(*columns).join(ProjectRecord, ProjectRecord.id == ProjectScheduleRecord.project_id)
    return stmt.where(*filters).order_by(ProjectScheduleRecord.created_at.asc(), ProjectScheduleRecord.id.asc())


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
    stmt = _build_project_schedules_stmt(
        ProjectScheduleRecord,
        schedule_id=schedule_id,
        project_id=project_id,
        project_ids=project_ids,
        organization_id=organization_id,
        disabled=disabled,
        scheduled_by_user_id=scheduled_by_user_id,
    )
    return (await session.execute(stmt)).scalars()


async def get_project_schedules_with_project_names_by(
    session: AsyncSession,
    *,
    project_id: str | None = None,
    organization_id: str | None = None,
) -> list[tuple[ProjectScheduleRecord, str]]:
    stmt = _build_project_schedules_stmt(
        ProjectScheduleRecord,
        ProjectRecord.name,
        project_id=project_id,
        organization_id=organization_id,
    )
    return [(schedule, project_name) for schedule, project_name in await session.execute(stmt)]
