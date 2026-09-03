from typing import TYPE_CHECKING
from uuid import uuid4

from sqlmodel import Field, Relationship, SQLModel

from .mixins import TimestampedModel

if TYPE_CHECKING:
    from src.modules.user.infra.db_models import UserRecord


class OrganizationRecord(TimestampedModel, SQLModel, table=True):
    __tablename__ = "organizations"

    id: str | None = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    name: str = Field(nullable=False, index=True, description="Organization name")
    description: str | None = Field(default=None, nullable=True, description="Organization description")
    inn: str | None = Field(default=None, nullable=True, index=True, unique=True, description="Organization INN")
    is_active: bool = Field(default=True, nullable=False, description="Is organization active")

    users: list["UserRecord"] = Relationship(back_populates="organization")
