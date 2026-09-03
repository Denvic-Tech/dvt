"""ADD DVT service file objects

Revision ID: 0055
Revises: 0054
Create Date: 2026-06-17 00:00:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Union

from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision: str = "0055"
down_revision: Union[str, Sequence[str], None] = "0054"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dvt_service_file_objects",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("organization_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("project_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("parent_path", sa.String(length=2048), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("is_dir", sa.Boolean(), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=True),
        sa.Column("content_type", sa.String(length=255), nullable=True),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(
            ["project_id", "organization_id"],
            ["projects.id", "projects.organization_id"],
            name="fk_dvt_service_files_project_organization",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "project_id",
            "parent_path",
            "name",
            name="uq_dvt_service_file_object_path",
        ),
    )
    op.create_index(
        op.f("ix_dvt_service_file_objects_organization_id"),
        "dvt_service_file_objects",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_dvt_service_file_objects_parent_path"),
        "dvt_service_file_objects",
        ["parent_path"],
        unique=False,
    )
    op.create_index(
        op.f("ix_dvt_service_file_objects_project_id"),
        "dvt_service_file_objects",
        ["project_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_dvt_service_file_objects_project_id"), table_name="dvt_service_file_objects")
    op.drop_index(op.f("ix_dvt_service_file_objects_parent_path"), table_name="dvt_service_file_objects")
    op.drop_index(op.f("ix_dvt_service_file_objects_organization_id"), table_name="dvt_service_file_objects")
    op.drop_table("dvt_service_file_objects")
