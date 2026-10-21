from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import sqlalchemy as sa
from sqlmodel import Field, SQLModel

from src.models.sa_types import JSONBCompat


def _utcnow() -> datetime:
    return datetime.now(UTC)


class DatasetRecord(SQLModel, table=True):
    """Каталожная сущность: один физический источник/приёмник в пределах организации."""

    __tablename__ = "datasets"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    organization_id: str = Field(
        sa_column=sa.Column(
            sa.String(),
            sa.ForeignKey("organizations.id"),
            nullable=False,
            index=True,
        )
    )
    kind: str = Field(sa_column=sa.Column(sa.String(length=64), nullable=False, index=True))
    physical_key: str = Field(sa_column=sa.Column(sa.Text(), nullable=False))
    location: str = Field(sa_column=sa.Column(sa.Text(), nullable=False))
    locator: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=sa.Column(JSONBCompat, nullable=False),
    )
    description: str | None = Field(default=None, sa_column=sa.Column(sa.Text(), nullable=True))
    description_updated_by: str | None = Field(
        default=None,
        sa_column=sa.Column(sa.String(), nullable=True),
    )
    description_updated_at: datetime | None = Field(
        default=None,
        sa_column=sa.Column(sa.DateTime(timezone=True), nullable=True),
    )
    schema_synced_at: datetime | None = Field(
        default=None,
        sa_column=sa.Column(sa.DateTime(timezone=True), nullable=True),
    )
    last_check_failed_at: datetime | None = Field(
        default=None,
        sa_column=sa.Column(sa.DateTime(timezone=True), nullable=True),
    )
    observed_at_run: datetime | None = Field(
        default=None,
        sa_column=sa.Column(sa.DateTime(timezone=True), nullable=True),
    )
    last_check_error: str | None = Field(default=None, sa_column=sa.Column(sa.Text(), nullable=True))
    last_check_error_kind: str | None = Field(
        default=None,
        sa_column=sa.Column(sa.String(length=32), nullable=True),
    )
    created_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=sa.Column(sa.DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=sa.Column(sa.DateTime(timezone=True), nullable=False),
    )

    __table_args__ = (
        sa.UniqueConstraint(
            "organization_id",
            "physical_key",
            name="uq_datasets_organization_physical_key",
        ),
    )


class DatasetFieldRecord(SQLModel, table=True):
    """Поле каталожной сущности: снэпшот схемы плюс место под описание."""

    __tablename__ = "dataset_fields"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    dataset_id: str = Field(
        sa_column=sa.Column(
            sa.String(),
            sa.ForeignKey("datasets.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    name: str = Field(sa_column=sa.Column(sa.String(length=512), nullable=False))
    dtype: str | None = Field(default=None, sa_column=sa.Column(sa.String(length=255), nullable=True))
    nullable: bool | None = Field(default=None, sa_column=sa.Column(sa.Boolean(), nullable=True))
    ordinal: int | None = Field(default=None, sa_column=sa.Column(sa.Integer(), nullable=True))
    primary_key: bool = Field(default=False, sa_column=sa.Column(sa.Boolean(), nullable=False))
    source_comment: str | None = Field(default=None, sa_column=sa.Column(sa.Text(), nullable=True))
    description: str | None = Field(default=None, sa_column=sa.Column(sa.Text(), nullable=True))
    description_updated_by: str | None = Field(
        default=None,
        sa_column=sa.Column(sa.String(), nullable=True),
    )
    description_updated_at: datetime | None = Field(
        default=None,
        sa_column=sa.Column(sa.DateTime(timezone=True), nullable=True),
    )
    status: str = Field(sa_column=sa.Column(sa.String(length=32), nullable=False))
    first_seen_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=sa.Column(sa.DateTime(timezone=True), nullable=False),
    )
    last_seen_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=sa.Column(sa.DateTime(timezone=True), nullable=False),
    )
    observed_via: list[str] = Field(
        default_factory=list,
        sa_column=sa.Column(JSONBCompat, nullable=False),
    )

    __table_args__ = (
        sa.UniqueConstraint("dataset_id", "name", name="uq_dataset_fields_dataset_name"),
    )


class DatasetConnectionRecord(SQLModel, table=True):
    """Через какие connection'ы наблюдалась сущность (M2M, без FK на внешнюю таблицу)."""

    __tablename__ = "dataset_connections"

    dataset_id: str = Field(
        sa_column=sa.Column(
            sa.String(),
            sa.ForeignKey("datasets.id", ondelete="CASCADE"),
            primary_key=True,
        )
    )
    connection_id: str = Field(
        sa_column=sa.Column(sa.String(), primary_key=True, index=True)
    )
    connection_revision: str = Field(sa_column=sa.Column(sa.String(length=64), nullable=False))
    first_seen_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=sa.Column(sa.DateTime(timezone=True), nullable=False),
    )
    last_seen_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=sa.Column(sa.DateTime(timezone=True), nullable=False),
    )


class DatasetLinkRecord(SQLModel, table=True):
    """Проекция «нода проекта читает/пишет сущность»."""

    __tablename__ = "dataset_links"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    dataset_id: str = Field(
        sa_column=sa.Column(
            sa.String(),
            sa.ForeignKey("datasets.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    project_id: str = Field(sa_column=sa.Column(sa.String(), nullable=False, index=True))
    organization_id: str = Field(sa_column=sa.Column(sa.String(), nullable=False))
    node_id: str = Field(sa_column=sa.Column(sa.String(), nullable=False))
    node_name: str = Field(sa_column=sa.Column(sa.String(length=255), nullable=False))
    direction: str = Field(sa_column=sa.Column(sa.String(length=16), nullable=False))
    kind: str = Field(sa_column=sa.Column(sa.String(length=16), nullable=False))
    resolved_via: str = Field(sa_column=sa.Column(sa.String(length=16), nullable=False))
    graph_revision: int = Field(sa_column=sa.Column(sa.Integer(), nullable=False))
    created_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=sa.Column(sa.DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=sa.Column(sa.DateTime(timezone=True), nullable=False),
    )

    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["project_id", "organization_id"],
            ["projects.id", "projects.organization_id"],
            name="fk_dataset_links_project_organization",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "project_id",
            "node_id",
            "direction",
            "dataset_id",
            name="uq_dataset_links_project_node_direction_dataset",
        ),
    )


class ProjectCatalogProjectionRecord(SQLModel, table=True):
    """Штамп и состояние последней пересборки каталожной проекции проекта."""

    __tablename__ = "project_catalog_projections"

    project_id: str = Field(sa_column=sa.Column(sa.String(), primary_key=True))
    organization_id: str = Field(sa_column=sa.Column(sa.String(), nullable=False))
    graph_revision: int = Field(sa_column=sa.Column(sa.Integer(), nullable=False))
    variables_fingerprint: str = Field(sa_column=sa.Column(sa.String(length=64), nullable=False))
    lineage_schema_version: int = Field(sa_column=sa.Column(sa.Integer(), nullable=False))
    depends_on_project_variables: bool = Field(
        default=False,
        sa_column=sa.Column(sa.Boolean(), nullable=False),
    )
    built_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=sa.Column(sa.DateTime(timezone=True), nullable=False),
    )
    status: str = Field(sa_column=sa.Column(sa.String(length=16), nullable=False))
    error: str | None = Field(default=None, sa_column=sa.Column(sa.Text(), nullable=True))
    diagnostics: list[dict[str, Any]] = Field(
        default_factory=list,
        sa_column=sa.Column(JSONBCompat, nullable=False),
    )

    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["project_id", "organization_id"],
            ["projects.id", "projects.organization_id"],
            name="fk_project_catalog_projections_project_organization",
            ondelete="CASCADE",
        ),
    )


PROJECTION_LINEAGE_COLUMN = "lineage"

# Документ lineage большой и нужен только use case lineage: колонка добавляется в таблицу, но не
# маппится на атрибут записи, поэтому выборки ProjectCatalogProjectionRecord её не загружают.
ProjectCatalogProjectionRecord.__table__.append_column(
    sa.Column(PROJECTION_LINEAGE_COLUMN, JSONBCompat, nullable=True)
)
