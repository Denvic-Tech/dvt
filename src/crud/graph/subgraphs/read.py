import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.pipeline_graph.infra.db_models import SubgraphRecord


async def get_subgraphs(
    session: AsyncSession,
    *filters: sa.ColumnExpressionArgument[bool],
) -> sa.ScalarResult[SubgraphRecord]:
    stmt = sa.select(SubgraphRecord).where(*filters)
    return (await session.execute(stmt)).scalars()


async def get_subgraphs_by(
    session: AsyncSession,
    organization_id: str | None = None,
    owner_user_id: str | None = None,
    project_id: str | None = None,
) -> sa.ScalarResult[SubgraphRecord]:
    filters = []

    if organization_id is not None:
        filters.append(SubgraphRecord.organization_id == organization_id)

    if owner_user_id is not None:
        filters.append(SubgraphRecord.user_id == owner_user_id)

    if project_id is not None:
        filters.append(SubgraphRecord.project_id == project_id)

    return await get_subgraphs(
        session,
        *filters,
    )
