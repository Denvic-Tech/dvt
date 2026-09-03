from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.pipeline_graph.infra.db_models import GraphNodeRecord


async def create_graph_nodes(
    session: AsyncSession,
    nodes: Sequence[GraphNodeRecord],
) -> Sequence[GraphNodeRecord]:
    session.add_all(nodes)
    await session.flush()
    return nodes
