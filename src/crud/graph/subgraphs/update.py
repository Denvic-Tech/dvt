from typing import Sequence
from datetime import datetime, UTC

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.pipeline_graph.infra.db_models import SubgraphRecord


async def update_subgraphs(
    session: AsyncSession,
    subgraphs: Sequence[SubgraphRecord],
) -> Sequence[SubgraphRecord]:
    now = datetime.now(tz=UTC)
    data = [
        (
            subgraph.id,
            subgraph.ui_id,
            subgraph.type,
            subgraph.position_x,
            subgraph.position_y,
            subgraph.selected,
            subgraph.expanded,
            subgraph.name,
            subgraph.display_name,
            subgraph.comment,
            subgraph.color,
            subgraph.project_id,
            subgraph.user_id,
        )
        for subgraph in subgraphs
    ]

    v = sa.values(
        sa.column("id", sa.String),
        sa.column("ui_id", sa.String),
        sa.column("type", sa.String),
        sa.column("position_x", sa.Float),
        sa.column("position_y", sa.Float),
        sa.column("selected", sa.Boolean),
        sa.column("expanded", sa.Boolean),
        sa.column("name", sa.String),
        sa.column("display_name", sa.String),
        sa.column("comment", sa.String),
        sa.column("color", sa.String),
        sa.column("project_id", sa.String),
        sa.column("user_id", sa.String),
        name="v",
    ).data(data)

    t = SubgraphRecord.__table__

    stmt = (
        sa.update(t)
        .where(
            sa.or_(
                t.c.id == v.c.id,
                t.c.ui_id == v.c.ui_id,
            ),
            t.c.project_id == v.c.project_id,
            t.c.user_id == v.c.user_id,
        )
        .values(
            type=sa.func.coalesce(v.c.type, t.c.type),
            position_x=sa.func.coalesce(sa.func.cast(v.c.position_x, sa.Float), t.c.position_x),
            position_y=sa.func.coalesce(sa.func.cast(v.c.position_y, sa.Float), t.c.position_y),
            selected=sa.func.coalesce(sa.func.cast(v.c.selected, sa.Boolean), t.c.selected),
            expanded=sa.func.coalesce(sa.func.cast(v.c.expanded, sa.Boolean), t.c.expanded),
            name=sa.func.coalesce(v.c.name, t.c.name),
            display_name=sa.func.coalesce(v.c.display_name, t.c.display_name),
            comment=sa.func.coalesce(v.c.comment, t.c.comment),
            color=sa.func.coalesce(v.c.color, t.c.color),
            updated_at=now,
        )
        .returning(t.c.id, t.c.ui_id)
    )

    res = (await session.execute(stmt)).all()

    return res
