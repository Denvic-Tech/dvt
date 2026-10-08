"""ADD data catalog tables

Revision ID: 0064
Revises: 0063
Create Date: 2026-10-07 00:00:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0064"
down_revision: Union[str, Sequence[str], None] = "0063"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLES_IN_DROP_ORDER = (
    "project_catalog_projections",
    "dataset_links",
    "dataset_connections",
    "dataset_fields",
    "datasets",
)


def _json_type() -> sa.types.TypeEngine:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        from sqlalchemy.dialects import postgresql

        return postgresql.JSONB(astext_type=sa.Text())
    return sa.JSON()


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def _has_index(table: str, index: str) -> bool:
    indexes = sa.inspect(op.get_bind()).get_indexes(table)
    return any(item.get("name") == index for item in indexes)


def _create_index(table: str, columns: list[str], *, name: str) -> None:
    if not _has_index(table, name):
        op.create_index(name, table, columns, unique=False)


def upgrade() -> None:
    json_type = _json_type()

    if not _has_table("datasets"):
        op.create_table(
            "datasets",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("organization_id", sa.String(), nullable=False),
            sa.Column("dialect", sa.String(length=64), nullable=False),
            sa.Column("host", sa.String(length=512), nullable=False),
            sa.Column("port", sa.Integer(), nullable=True),
            sa.Column("database", sa.String(length=512), nullable=True),
            sa.Column("schema", sa.String(length=512), nullable=True),
            sa.Column("table", sa.String(length=512), nullable=False),
            sa.Column("physical_key", sa.Text(), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("schema_synced_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_check_failed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "organization_id",
                "physical_key",
                name="uq_datasets_organization_physical_key",
            ),
        )
    _create_index("datasets", ["organization_id"], name=op.f("ix_datasets_organization_id"))

    if not _has_table("dataset_fields"):
        op.create_table(
            "dataset_fields",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("dataset_id", sa.String(), nullable=False),
            sa.Column("name", sa.String(length=512), nullable=False),
            sa.Column("dtype", sa.String(length=255), nullable=True),
            sa.Column("nullable", sa.Boolean(), nullable=True),
            sa.Column("ordinal", sa.Integer(), nullable=True),
            sa.Column("primary_key", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("source_comment", sa.Text(), nullable=True),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("observed_via", json_type, nullable=False),
            sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("dataset_id", "name", name="uq_dataset_fields_dataset_name"),
        )
    _create_index("dataset_fields", ["dataset_id"], name=op.f("ix_dataset_fields_dataset_id"))

    if not _has_table("dataset_connections"):
        op.create_table(
            "dataset_connections",
            sa.Column("dataset_id", sa.String(), nullable=False),
            sa.Column("connection_id", sa.String(), nullable=False),
            sa.Column("connection_revision", sa.String(length=64), nullable=False),
            sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("dataset_id", "connection_id"),
        )
    _create_index(
        "dataset_connections",
        ["connection_id"],
        name=op.f("ix_dataset_connections_connection_id"),
    )

    if not _has_table("dataset_links"):
        op.create_table(
            "dataset_links",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("dataset_id", sa.String(), nullable=False),
            sa.Column("project_id", sa.String(), nullable=False),
            sa.Column("organization_id", sa.String(), nullable=False),
            sa.Column("node_id", sa.String(), nullable=False),
            sa.Column("node_name", sa.String(length=255), nullable=False),
            sa.Column("direction", sa.String(length=16), nullable=False),
            sa.Column("kind", sa.String(length=16), nullable=False),
            sa.Column("resolved_via", sa.String(length=16), nullable=False),
            sa.Column("graph_revision", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["project_id", "organization_id"],
                ["projects.id", "projects.organization_id"],
                name="fk_dataset_links_project_organization",
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "project_id",
                "node_id",
                "direction",
                "dataset_id",
                name="uq_dataset_links_project_node_direction_dataset",
            ),
        )
    _create_index("dataset_links", ["dataset_id"], name=op.f("ix_dataset_links_dataset_id"))
    _create_index("dataset_links", ["project_id"], name=op.f("ix_dataset_links_project_id"))

    if not _has_table("project_catalog_projections"):
        op.create_table(
            "project_catalog_projections",
            sa.Column("project_id", sa.String(), nullable=False),
            sa.Column("organization_id", sa.String(), nullable=False),
            sa.Column("graph_revision", sa.Integer(), nullable=False),
            sa.Column("variables_fingerprint", sa.String(length=64), nullable=False),
            sa.Column("lineage_schema_version", sa.Integer(), nullable=False),
            sa.Column(
                "depends_on_project_variables",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
            sa.Column("built_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("status", sa.String(length=16), nullable=False),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("diagnostics", json_type, nullable=False),
            sa.ForeignKeyConstraint(
                ["project_id", "organization_id"],
                ["projects.id", "projects.organization_id"],
                name="fk_project_catalog_projections_project_organization",
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("project_id"),
        )


def downgrade() -> None:
    for table in _TABLES_IN_DROP_ORDER:
        if _has_table(table):
            op.drop_table(table)
