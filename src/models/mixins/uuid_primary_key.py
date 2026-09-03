from uuid import UUID, uuid4

from sqlmodel import SQLModel, Field


class UUIDPrimaryKeyMixin(SQLModel):
    id: UUID = Field(default_factory=uuid4, primary_key=True, nullable=False)
