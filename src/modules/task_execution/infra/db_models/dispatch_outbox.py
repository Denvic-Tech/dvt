from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


class TaskDispatchOutboxRecord(SQLModel, table=True):
    """Transactional outbox for pipeline execution delivery."""

    __tablename__ = "task_dispatch_outbox"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    task_id: str = Field(
        sa_column=Column(
            String,
            ForeignKey("tasks.task_id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
            index=True,
        )
    )
    payload: dict = Field(sa_column=Column(JSON, nullable=False))
    status: str = Field(default="PENDING", sa_column=Column(String, nullable=False, index=True))
    created_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    published_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    attempts: int = Field(default=0, sa_column=Column(Integer, nullable=False, default=0))
    last_error: str | None = Field(default=None, sa_column=Column(String, nullable=True))
