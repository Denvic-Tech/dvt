from uuid import uuid4

from sqlmodel import Field, SQLModel

from core.types import Column

from .mixins import TimestampedModel
from .sa_types import PydanticType


class QueueTopicRecord(TimestampedModel, SQLModel, table=True):
    __tablename__ = "queue_topics"

    id: str | None = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    name: str = Field(nullable=True, description="Name of the topic", index=True)

    columns_schema: list[Column] = Field(
        nullable=False,
        description="Data's schema of the topic",
        sa_type=PydanticType(list[Column]),
    )
