from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import Column
from sqlmodel import Field, Relationship
from usrak.core.models.tokens import TokensModelBase

from .sa_types import JSONBCompat

if TYPE_CHECKING:
    from src.modules.user.infra.db_models import UserRecord


class UsersTokenRecord(TokensModelBase, table=True):
    """Модель токенов пользователя для БД"""

    __tablename__ = "users_tokens"
    __owner_field_name__ = "user_id"

    id: str | None = Field(default_factory=lambda: str(uuid4()), primary_key=True)

    whitelisted_ip_addresses: list[str] | None = Field(
        default=None,
        sa_column=Column(JSONBCompat, nullable=True),
        description="List of whitelisted IP addresses",
    )

    access_scope: dict | None = Field(
        default=None,
        sa_column=Column(JSONBCompat, nullable=True),
        description="Versioned access scope for purpose-specific tokens such as MCP",
    )

    user_id: str = Field(foreign_key="users.id", index=True, nullable=False)
    user: "UserRecord" = Relationship(back_populates="tokens")
