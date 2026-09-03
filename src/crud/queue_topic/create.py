from sqlalchemy.ext.asyncio import AsyncSession

from core.types import Column
from src.models import QueueTopicRecord


async def create_queue_topic(
        session: AsyncSession,
        *,
        name: str,
        columns_schema: list[Column],
) -> QueueTopicRecord:
    """Persist a queue topic in storage."""
    entry = QueueTopicRecord(
        name=name,
        columns_schema=columns_schema,
    )
    session.add(entry)
    await session.flush([entry])
    return entry
