from typing import Sequence

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.pipeline_graph.infra.db_models import GraphEdgeRecord


async def get_graph_edges(
    session: AsyncSession,
    *filters: sa.ColumnExpressionArgument[bool],
) -> Sequence[GraphEdgeRecord]:
    stmt = sa.select(GraphEdgeRecord).where(*filters)
    return (await session.execute(stmt)).scalars().all()


async def get_graph_edges_by(
    session: AsyncSession,
    organization_id: str | None = None,
    owner_user_id: str | None = None,
    project_id: str | None = None,
) -> Sequence[GraphEdgeRecord]:

    filters = []

    if organization_id is not None:
        filters.append(GraphEdgeRecord.organization_id == organization_id)

    if owner_user_id is not None:
        filters.append(GraphEdgeRecord.user_id == owner_user_id)

    if project_id is not None:
        filters.append(GraphEdgeRecord.project_id == project_id)

    return await get_graph_edges(
        session,
        *filters,
    )
