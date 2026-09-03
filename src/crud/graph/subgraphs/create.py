from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.pipeline_graph.infra.db_models import SubgraphRecord


async def create_subgraphs(
    session: AsyncSession,
    subgraphs: Sequence[SubgraphRecord],
) -> Sequence[SubgraphRecord]:
    session.add_all(subgraphs)
    await session.flush()
    return subgraphs
