"""Add created/updated timestamps to graph entities

Revision ID: 0009
Revises: 0008
Create Date: 2025-11-05 10:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: Union[str, Sequence[str], None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    now = sa.func.now()

    op.add_column(
        "graph_nodes",
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False, server_default=now),
    )
    op.add_column(
        "graph_nodes",
        sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False, server_default=now),
    )
    op.add_column(
        "graph_edges",
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False, server_default=now),
    )
    op.add_column(
        "graph_edges",
        sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False, server_default=now),
    )

    op.alter_column("graph_nodes", "created_at", server_default=None)
    op.alter_column("graph_nodes", "updated_at", server_default=None)
    op.alter_column("graph_edges", "created_at", server_default=None)
    op.alter_column("graph_edges", "updated_at", server_default=None)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("graph_edges", "updated_at")
    op.drop_column("graph_edges", "created_at")
    op.drop_column("graph_nodes", "updated_at")
    op.drop_column("graph_nodes", "created_at")
