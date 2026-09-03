from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy import Column, ForeignKeyConstraint, UniqueConstraint
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


class DVTServiceFileObjectRecord(SQLModel, table=True):
    __tablename__ = "dvt_service_file_objects"

    id: str | None = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    organization_id: str = Field(foreign_key="organizations.id", nullable=False, index=True)
    project_id: str = Field(nullable=False, index=True)
    parent_path: str = Field(default="", nullable=False, index=True, max_length=2048)
    name: str = Field(nullable=False, max_length=255)
    is_dir: bool = Field(default=False, nullable=False)
    content: bytes | None = Field(default=None, sa_column=Column(sa.LargeBinary, nullable=True))
    content_type: str | None = Field(default=None, max_length=255)
    size: int = Field(default=0, nullable=False, ge=0)
    sha256: str | None = Field(default=None, max_length=64)
    created_at: datetime = Field(default_factory=_utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=_utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "project_id",
            "parent_path",
            "name",
            name="uq_dvt_service_file_object_path",
        ),
        ForeignKeyConstraint(
            ["project_id", "organization_id"],
            ["projects.id", "projects.organization_id"],
            name="fk_dvt_service_files_project_organization",
            ondelete="CASCADE",
        ),
    )
