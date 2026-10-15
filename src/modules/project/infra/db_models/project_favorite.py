from datetime import UTC, datetime

import sqlalchemy as sa
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


class ProjectFavoriteRecord(SQLModel, table=True):
    """Персональная отметка «избранный проект» для пользователя."""

    __tablename__ = "project_favorites"

    user_id: str = Field(
        sa_column=sa.Column(
            sa.String,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        description="ID пользователя, добавившего проект в избранное",
    )
    project_id: str = Field(
        sa_column=sa.Column(
            sa.String,
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
            index=True,
        ),
        description="ID избранного проекта",
    )
    created_at: datetime = Field(
        default_factory=_utcnow,
        nullable=False,
        description="Время добавления проекта в избранное",
    )
