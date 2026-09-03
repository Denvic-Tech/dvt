from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.mixins import ModelWithUIID
from src.modules.pipeline_graph.infra.db_models import SubgraphRecord


async def delete_subgraphs(
    session: AsyncSession,
    subgraphs: Sequence[SubgraphRecord],
) -> Sequence[SubgraphRecord]:
    for subgraph in subgraphs:
        await session.delete(subgraph)
    await session.flush()
    return subgraphs


async def delete_subgraphs_by(
    session: AsyncSession,
    project_id: str | None = None,
    user_id: str | None = None,
    id: str | Sequence[str] | None = None,
    ui_id: str | Sequence[str] | None = None,
) -> Sequence[ModelWithUIID[str]]:
    if isinstance(id, str):
        id = [id]

    if isinstance(ui_id, str):
        ui_id = [ui_id]

    filters = []

    if project_id:
        filters.append(SubgraphRecord.project_id == project_id)

    if user_id:
        filters.append(SubgraphRecord.user_id == user_id)

    if id:
        filters.append(SubgraphRecord.id.in_(id))

    if ui_id:
        filters.append(SubgraphRecord.ui_id.in_(ui_id))

    stmt = (
        sa.delete(SubgraphRecord)
        .where(*filters)
        .returning(SubgraphRecord.id, SubgraphRecord.ui_id)
    )
    result = (await session.execute(stmt)).all()

    await session.flush()

    return [ModelWithUIID[str](id=row.id, ui_id=row.ui_id) for row in result]
