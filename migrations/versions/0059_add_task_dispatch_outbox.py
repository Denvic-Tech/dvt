"""Add durable task execution dispatch outbox.

Revision ID: 0059
Revises: 0058
Create Date: 2026-08-17 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0059"
down_revision: Union[str, Sequence[str], None] = "0058"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "task_dispatch_outbox",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("task_id", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="PENDING"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.task_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", name="uq_task_dispatch_outbox_task_id"),
    )
    op.create_index("ix_task_dispatch_outbox_status", "task_dispatch_outbox", ["status"])


def downgrade() -> None:
    op.drop_index("ix_task_dispatch_outbox_status", table_name="task_dispatch_outbox")
    op.drop_table("task_dispatch_outbox")
