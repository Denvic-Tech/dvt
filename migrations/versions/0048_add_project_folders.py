"""add project folders

Revision ID: 0048
Revises: 0047
Create Date: 2026-05-13 15:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision: str = "0048"
down_revision: Union[str, Sequence[str], None] = "0047"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "project_folders",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("parent_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("user_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("organization_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False),
        sa.CheckConstraint("id != parent_id", name="check_project_folders_not_self_parent"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["parent_id", "organization_id"],
            ["project_folders.id", "project_folders.organization_id"],
            name="fk_project_folders_parent_organization",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "organization_id", name="unique_project_folder_id_organization_id"),
    )
    op.create_index(op.f("ix_project_folders_name"), "project_folders", ["name"], unique=False)
    op.create_index(op.f("ix_project_folders_parent_id"), "project_folders", ["parent_id"], unique=False)
    op.create_index(op.f("ix_project_folders_user_id"), "project_folders", ["user_id"], unique=False)
    op.create_index(
        op.f("ix_project_folders_organization_id"),
        "project_folders",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        "ix_project_folders_org_parent_deleted",
        "project_folders",
        ["organization_id", "parent_id", "is_deleted"],
        unique=False,
    )
    op.create_index(
        "ix_project_folders_org_user_parent_deleted",
        "project_folders",
        ["organization_id", "user_id", "parent_id", "is_deleted"],
        unique=False,
    )

    op.add_column(
        "projects",
        sa.Column("folder_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    )
    op.create_index(op.f("ix_projects_folder_id"), "projects", ["folder_id"], unique=False)
    op.create_foreign_key(
        "fk_projects_folder",
        "projects",
        "project_folders",
        ["folder_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_projects_folder", "projects", type_="foreignkey")
    op.drop_index(op.f("ix_projects_folder_id"), table_name="projects")
    op.drop_column("projects", "folder_id")

    op.drop_index("ix_project_folders_org_user_parent_deleted", table_name="project_folders")
    op.drop_index("ix_project_folders_org_parent_deleted", table_name="project_folders")
    op.drop_index(op.f("ix_project_folders_organization_id"), table_name="project_folders")
    op.drop_index(op.f("ix_project_folders_user_id"), table_name="project_folders")
    op.drop_index(op.f("ix_project_folders_parent_id"), table_name="project_folders")
    op.drop_index(op.f("ix_project_folders_name"), table_name="project_folders")
    op.drop_table("project_folders")
