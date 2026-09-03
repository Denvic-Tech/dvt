from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql._typing import _ColumnsClauseArgument

from src.modules.project.infra.db_models import ProjectRecord
from src.modules.user.infra.db_models import UserRecord


def _get_projects_statement(
    select: _ColumnsClauseArgument = ProjectRecord,
    organization_id: str | None = None,
    owner_user_id: str | None = None,
    project_id: str | None = None,
):
    filters: list[sa.ColumnExpressionArgument[bool]] = []

    if organization_id is not None:
        filters.append(ProjectRecord.organization_id == organization_id)

    if owner_user_id is not None:
        filters.append(ProjectRecord.user_id == owner_user_id)

    if project_id is not None:
        filters.append(ProjectRecord.id == project_id)

    statement = sa.select(select)

    if select is not ProjectRecord:
        statement = statement.select_from(ProjectRecord)

    return statement.where(*filters)


async def get_projects(
    session: AsyncSession,
    *filters: sa.ColumnExpressionArgument[bool],
) -> sa.ScalarResult[ProjectRecord]:
    stmt = sa.select(ProjectRecord).where(*filters)
    return (await session.execute(stmt)).scalars()


async def get_projects_by(
    session: AsyncSession,
    organization_id: str | None = None,
    owner_user_id: str | None = None,
    project_id: str | None = None,
) -> sa.ScalarResult[ProjectRecord]:
    statement = _get_projects_statement(
        organization_id=organization_id,
        owner_user_id=owner_user_id,
        project_id=project_id,
    )

    return (await session.execute(statement)).scalars()


async def get_projects_by_ids(
    session: AsyncSession,
    *,
    project_ids: Sequence[str],
    organization_id: str | None = None,
    owner_user_id: str | None = None,
) -> list[ProjectRecord]:
    if not project_ids:
        return []

    statement = _get_projects_statement(
        organization_id=organization_id,
        owner_user_id=owner_user_id,
    ).where(
        ProjectRecord.id.in_(project_ids),
        ProjectRecord.is_deleted == False,
    )

    return list((await session.execute(statement)).scalars().all())


async def get_user_emails_by_ids(
    session: AsyncSession,
    *,
    user_ids: Sequence[str | None],
) -> dict[str, str | None]:
    normalized_user_ids = tuple(dict.fromkeys(user_id for user_id in user_ids if user_id))
    if not normalized_user_ids:
        return {}

    rows = (
        await session.execute(
            sa.select(UserRecord.id, UserRecord.email).where(UserRecord.id.in_(normalized_user_ids))
        )
    ).all()
    return {row.id: row.email for row in rows}


async def get_projects_count(
    session: AsyncSession,
    organization_id: str | None = None,
    owner_user_id: str | None = None,
    project_id: str | None = None,
) -> int:
    statement = _get_projects_statement(
        select=sa.func.count(),
        organization_id=organization_id,
        owner_user_id=owner_user_id,
        project_id=project_id,
    )
    return (await session.execute(statement)).scalar_one()
