from typing import Sequence

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import QueueTopicRecord


async def delete_queue_topics(
        session: AsyncSession,
        topics: Sequence[QueueTopicRecord],
) -> Sequence[QueueTopicRecord]:
    for topic in topics:
        await session.delete(topic)
    await session.flush()
    return topics


async def delete_queue_topics_by(
        session: AsyncSession,
        *,
        topic_id: str | list[str] | None = None,
        name: str | list[str] | None = None,
) -> list[str]:
    if isinstance(topic_id, str):
        topic_id = [topic_id]

    if isinstance(name, str):
        name = [name]

    filters: list[sa.ColumnExpressionArgument[bool]] = []

    if topic_id:
        filters.append(QueueTopicRecord.id.in_(topic_id))

    if name:
        filters.append(QueueTopicRecord.name.in_(name))

    stmt = sa.delete(QueueTopicRecord).where(*filters).returning(QueueTopicRecord.id)
    result = (await session.execute(stmt)).scalars().all()
    await session.flush()
    return list(result)
