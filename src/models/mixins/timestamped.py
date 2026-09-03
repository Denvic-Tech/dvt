from datetime import datetime, timezone

from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    """Return naive UTC timestamp to keep consistency with existing schema."""
    return datetime.now(tz=timezone.utc)


class TimestampedModel(SQLModel, table=False):
    """Mixin that adds `created_at` and `updated_at` columns with automatic timestamps."""

    created_at: datetime = Field(
        default_factory=_utcnow,
        nullable=False,
        description="Timestamp when the record was created",
    )
    updated_at: datetime = Field(
        default_factory=_utcnow,
        nullable=False,
        sa_column_kwargs={"onupdate": _utcnow},
        description="Timestamp when the record was last updated",
    )
