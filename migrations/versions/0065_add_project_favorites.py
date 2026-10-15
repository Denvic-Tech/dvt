"""ADD project favorites and tasks queued_at index

Revision ID: 0065
Revises: 0064
Create Date: 2026-10-13 00:00:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0065"
down_revision: Union[str, Sequence[str], None] = "0064"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "project_favorites",
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "project_id"),
    )
    op.create_index(
        "ix_project_favorites_project_id",
        "project_favorites",
        ["project_id"],
        unique=False,
    )
    op.create_index("ix_tasks_queued_at", "tasks", ["queued_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_tasks_queued_at", table_name="tasks")
    op.drop_index("ix_project_favorites_project_id", table_name="project_favorites")
    op.drop_table("project_favorites")
