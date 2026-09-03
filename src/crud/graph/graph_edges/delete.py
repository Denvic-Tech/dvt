from typing import Sequence

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.pipeline_graph.infra.db_models import GraphEdgeRecord


async def delete_graph_edges(
    session: AsyncSession,
    edges: Sequence[GraphEdgeRecord],
) -> Sequence[GraphEdgeRecord]:
    for edge in edges:
        await session.delete(edge)
    await session.flush()
    return edges


async def delete_graph_edges_by(
    session: AsyncSession,
    project_id: str | None = None,
    user_id: str | None = None,
    id: str | Sequence[str] | None = None,
    ui_id: str | Sequence[str] | None = None,
) -> Sequence[GraphEdgeRecord]:
    if isinstance(id, str):
        id = [id]

    if isinstance(ui_id, str):
        ui_id = [ui_id]

    filters = []

    if project_id:
        filters.append(GraphEdgeRecord.project_id == project_id)

    if user_id:
        filters.append(GraphEdgeRecord.user_id == user_id)

    if id:
        filters.append(GraphEdgeRecord.id.in_(id))

    if ui_id:
        filters.append(GraphEdgeRecord.ui_id.in_(ui_id))

    stmt = (
        sa.delete(GraphEdgeRecord)
        .where(*filters)
        .returning(GraphEdgeRecord)
    )
    result = (await session.execute(stmt)).scalars().all()

    await session.flush()

    return result
