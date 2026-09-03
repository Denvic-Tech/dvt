"""Add persistent project graph dirty state.

Revision ID: 0057
Revises: 0056
Create Date: 2026-08-03 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0057"
down_revision: Union[str, Sequence[str], None] = "0056"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("dirty_node_ids", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
    )
    op.add_column(
        "projects",
        sa.Column("graph_revision", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.create_check_constraint(
        "check_graph_revision_non_negative",
        "projects",
        "graph_revision >= 0",
    )


def downgrade() -> None:
    op.drop_constraint("check_graph_revision_non_negative", "projects", type_="check")
    op.drop_column("projects", "graph_revision")
    op.drop_column("projects", "dirty_node_ids")
