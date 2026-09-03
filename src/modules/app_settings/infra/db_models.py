from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from sqlmodel import Field, SQLModel


class AppSettingValueRecord(SQLModel, table=True):
    __tablename__ = "app_setting_values"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    key: str = Field(sa_column=sa.Column(sa.String(length=255), nullable=False, unique=True, index=True))
    value: str | None = Field(default=None, sa_column=sa.Column(sa.Text(), nullable=True))
    version: int = Field(default=1, sa_column=sa.Column(sa.Integer(), nullable=False))
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=sa.Column(sa.DateTime(timezone=True), nullable=False),
    )
    updated_by: str | None = Field(default=None, sa_column=sa.Column(sa.String(length=255), nullable=True))


class AppSettingChangeRecord(SQLModel, table=True):
    __tablename__ = "app_setting_changes"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    key: str = Field(sa_column=sa.Column(sa.String(length=255), nullable=False, index=True))
    old_value: str | None = Field(default=None, sa_column=sa.Column(sa.Text(), nullable=True))
    new_value: str | None = Field(default=None, sa_column=sa.Column(sa.Text(), nullable=True))
    changed_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=sa.Column(sa.DateTime(timezone=True), nullable=False, index=True),
    )
    changed_by: str | None = Field(default=None, sa_column=sa.Column(sa.String(length=255), nullable=True))
    change_reason: str | None = Field(default=None, sa_column=sa.Column(sa.Text(), nullable=True))
