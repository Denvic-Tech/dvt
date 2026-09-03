from typing import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.pipeline_graph.infra.db_models import GraphEdgeRecord


async def create_graph_edges(
    session: AsyncSession,
    edges: Sequence[GraphEdgeRecord],
) -> Sequence[GraphEdgeRecord]:
    session.add_all(edges)
    await session.flush()
    return edges
