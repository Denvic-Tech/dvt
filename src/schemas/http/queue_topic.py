from typing import Dict, List, Any

from pydantic import BaseModel
from pystructor import omit, partial

from src.models.queue_topic import QueueTopicRecord


@omit(QueueTopicRecord, "id", "created_at", "updated_at")
class QueueTopicCreateSchema(BaseModel):
    """Schema for creating a queue topic."""


@omit(QueueTopicRecord)
class QueueTopicReadSchema(BaseModel):
    """Schema for reading a queue topic."""

    class Config:
        from_attributes = True


@partial(QueueTopicCreateSchema)
class QueueTopicUpdateSchema(BaseModel):
    """Schema for updating a queue topic."""


class QueueTopicDataSchema(BaseModel):
    data: List[Dict[str, Any]]


class QueueTopicDataSuccessSchema(BaseModel):
    success: bool
    message: str
    stored_count: int
