from typing import Sequence
from datetime import datetime, UTC

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.pipeline_graph.infra.db_models import GraphEdgeRecord
from src.constants import UNSET


def _nullable_expr(v_col, t_col):
    """
    CASE WHEN v.col = sentinel THEN t.col   -- не передано, оставить старое
         ELSE v.col                          -- передано (включая NULL), записать
    END
    """
    return sa.case(
        (v_col == UNSET, t_col),
        else_=v_col,
    )


async def update_graph_edges(
    session: AsyncSession,
    edges: Sequence[GraphEdgeRecord],
) -> Sequence[sa.Row[GraphEdgeRecord]]:
    now = datetime.now(tz=UTC)

    data = []
    for edge in edges:
        fields_set = edge.model_fields_set
        data.append((
            edge.id,
            edge.ui_id,
            edge.type,
            edge.source,
            edge.source_handle,
            edge.target,
            edge.target_handle,
            edge.subgraph_id if "subgraph_id" in fields_set else UNSET,
            edge.project_id,
            edge.user_id,
        ))

    v = sa.values(
        sa.column("id", sa.String),
        sa.column("ui_id", sa.String),
        sa.column("type", sa.String),
        sa.column("source", sa.String),
        sa.column("source_handle", sa.String),
        sa.column("target", sa.String),
        sa.column("target_handle", sa.String),
        sa.column("subgraph_id", sa.String),
        sa.column("project_id", sa.String),
        sa.column("user_id", sa.String),
        name="v",
    ).data(data)

    t = GraphEdgeRecord.__table__

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
            source=sa.func.coalesce(v.c.source, t.c.source),
            source_handle=sa.func.coalesce(v.c.source_handle, t.c.source_handle),
            target=sa.func.coalesce(v.c.target, t.c.target),
            target_handle=sa.func.coalesce(v.c.target_handle, t.c.target_handle),
            subgraph_id=_nullable_expr(v.c.subgraph_id, t.c.subgraph_id),
            updated_at=now,
        )
        .returning(t.c.id, t.c.ui_id)
    )

    res = (await session.execute(stmt)).all()

    return res
