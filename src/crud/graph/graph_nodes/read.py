import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.pipeline_graph.infra.db_models import GraphNodeRecord


async def get_graph_nodes(
    session: AsyncSession,
    *filters: sa.ColumnExpressionArgument[bool],
) -> sa.ScalarResult[GraphNodeRecord]:
    stmt = sa.select(GraphNodeRecord).where(*filters)
    return (await session.execute(stmt)).scalars()


async def get_graph_nodes_by(
    session: AsyncSession,
    organization_id: str | None = None,
    owner_user_id: str | None = None,
    project_id: str | None = None,
) -> sa.ScalarResult[GraphNodeRecord]:
    filters = []

    if organization_id is not None:
        filters.append(GraphNodeRecord.organization_id == organization_id)

    if owner_user_id is not None:
        filters.append(GraphNodeRecord.user_id == owner_user_id)

    if project_id is not None:
        filters.append(GraphNodeRecord.project_id == project_id)

    return await get_graph_nodes(
        session,
        *filters,
    )
