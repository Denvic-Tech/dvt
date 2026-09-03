import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import QueueTopicRecord


async def get_queue_topics(
        session: AsyncSession,
        *filters: sa.ColumnExpressionArgument[bool],
) -> sa.ScalarResult[QueueTopicRecord]:
    stmt = sa.select(QueueTopicRecord).where(*filters)
    return (await session.execute(stmt)).scalars()


async def get_queue_topics_by(
        session: AsyncSession,
        topic_id: str | None = None,
        name: str | None = None,
) -> sa.ScalarResult[QueueTopicRecord]:
    filters: list[sa.ColumnExpressionArgument[bool]] = []

    if topic_id is not None:
        filters.append(QueueTopicRecord.id == topic_id)

    if name is not None:
        filters.append(QueueTopicRecord.name == name)

    return await get_queue_topics(session, *filters)
