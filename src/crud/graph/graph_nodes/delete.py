from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.mixins import ModelWithUIID
from src.modules.pipeline_graph.infra.db_models import GraphNodeRecord


async def delete_graph_nodes(
    session: AsyncSession,
    nodes: Sequence[GraphNodeRecord],
) -> Sequence[GraphNodeRecord]:
    for node in nodes:
        await session.delete(node)
    await session.flush()
    return nodes


async def delete_graph_nodes_by(
    session: AsyncSession,
    project_id: str | None = None,
    user_id: str | None = None,
    id: str | list[str] | None = None,
    ui_id: str | list[str] | None = None,
) -> Sequence[ModelWithUIID[str]]:
    if isinstance(id, str):
        id = [id]

    if isinstance(ui_id, str):
        ui_id = [ui_id]

    filters = []

    if project_id:
        filters.append(GraphNodeRecord.project_id == project_id)

    if user_id:
        filters.append(GraphNodeRecord.user_id == user_id)

    if id:
        filters.append(GraphNodeRecord.id.in_(id))

    if ui_id:
        filters.append(GraphNodeRecord.ui_id.in_(ui_id))

    stmt = (
        sa.delete(GraphNodeRecord)
        .where(*filters)
        .returning(GraphNodeRecord.id, GraphNodeRecord.ui_id)
    )
    result = (await session.execute(stmt)).all()

    await session.flush()

    return [ModelWithUIID[str](id=row.id, ui_id=row.ui_id) for row in result]
