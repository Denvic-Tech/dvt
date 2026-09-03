from typing import TYPE_CHECKING
from uuid import uuid4

import sqlalchemy as sa
from sqlmodel import Field, Relationship
from usrak import UserModelBase

from src import enums
from src.models.user_tokens import UsersTokenRecord

if TYPE_CHECKING:
    from src.models import OrganizationRecord


class UserRecord(UserModelBase, table=True):
    """Модель пользователя для БД"""

    __tablename__ = "users"
    __id_field_name__ = "id"

    id: str | None = Field(default_factory=lambda: str(uuid4()), primary_key=True)

    role: enums.DVTDefaultRoles | str = Field(
        sa_column=sa.Column(sa.String, index=True, nullable=False),
        default=enums.DVTDefaultRoles.USER,
    )

    organization_id: str = Field(
        foreign_key="organizations.id",
        nullable=False,
        index=True,
        description="ID организации пользователя",
    )
    organization: "OrganizationRecord" = Relationship(back_populates="users")

    tokens: list[UsersTokenRecord] = Relationship(
        back_populates="user",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )
