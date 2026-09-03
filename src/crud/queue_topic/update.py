from datetime import datetime, UTC

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from core.types import Column
from src.models import QueueTopicRecord


async def update_queue_topic(
        session: AsyncSession,
        *,
        topic_id: str,
        name: str | None = None,
        columns_schema: list[Column] | None = None,
) -> QueueTopicRecord | None:
    stmt = sa.select(QueueTopicRecord).where(QueueTopicRecord.id == topic_id).limit(1)
    topic: QueueTopicRecord | None = (await session.execute(stmt)).scalars().first()

    if topic is None:
        return None

    if name is not None:
        topic.name = name

    if columns_schema is not None:
        topic.columns_schema = columns_schema

    topic.updated_at = datetime.now(tz=UTC)
    session.add(topic)
    await session.flush([topic])
    return topic
