from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql._typing import _ColumnsClauseArgument

from src.crud.organization._session import maybe_await
from src.models import OrganizationRecord
from src.modules.project.infra.db_models import ProjectRecord


def _get_organizations_statement(
    select: _ColumnsClauseArgument = OrganizationRecord,
    organization_id: str | None = None,
    inn: str | None = None,
):
    filters: list[sa.ColumnExpressionArgument[bool]] = []

    if organization_id is not None:
        filters.append(OrganizationRecord.id == organization_id)

    if inn is not None:
        filters.append(OrganizationRecord.inn == inn)

    statement = sa.select(select)

    if select is not OrganizationRecord:
        statement = statement.select_from(OrganizationRecord)

    return statement.where(*filters).order_by(OrganizationRecord.created_at.asc(), OrganizationRecord.id.asc())


async def get_organizations(
    session: AsyncSession,
    *filters: sa.ColumnExpressionArgument[bool],
) -> sa.ScalarResult[OrganizationRecord]:
    stmt = sa.select(OrganizationRecord).where(*filters).order_by(OrganizationRecord.created_at.asc(), OrganizationRecord.id.asc())
    return (await maybe_await(session.execute(stmt))).scalars()


async def get_organizations_by(
    session: AsyncSession,
    organization_id: str | None = None,
    inn: str | None = None,
) -> sa.ScalarResult[OrganizationRecord]:
    statement = _get_organizations_statement(
        organization_id=organization_id,
        inn=inn,
    )
    return (await maybe_await(session.execute(statement))).scalars()


async def get_projects_count_by_organization_ids(
    session: AsyncSession,
    *,
    organization_ids: Sequence[str],
) -> dict[str, int]:
    normalized_organization_ids = list(dict.fromkeys(org_id for org_id in organization_ids if org_id))
    if not normalized_organization_ids:
        return {}

    stmt = (
        sa.select(ProjectRecord.organization_id, sa.func.count().label("projects_count"))
        .where(
            ProjectRecord.organization_id.in_(normalized_organization_ids),
            ProjectRecord.is_deleted == False,
        )
        .group_by(ProjectRecord.organization_id)
    )
    rows = (await maybe_await(session.execute(stmt))).all()
    counts = {org_id: 0 for org_id in normalized_organization_ids}
    counts.update({row.organization_id: row.projects_count for row in rows})
    return counts

