"""ADD node port observations table

Revision ID: 0068
Revises: 0067
Create Date: 2026-10-27 00:00:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0068"
down_revision: Union[str, Sequence[str], None] = "0067"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "node_port_observations"
_PROJECT_INDEX = "ix_node_port_observations_project_id"


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


def upgrade() -> None:
    if not _has_table(_TABLE):
        # Состав колонок DataFrame-выхода ноды, наблюдённый воркером при прогоне. Живёт вместе
        # с нодой: составной FK на (ui_id, project_id) удаляет строки при удалении ноды.
        op.create_table(
            _TABLE,
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("project_id", sa.String(), nullable=False),
            sa.Column("node_id", sa.String(), nullable=False),
            sa.Column("port", sa.String(length=128), nullable=False),
            sa.Column("columns", _json_type(), nullable=False),
            sa.Column("graph_revision", sa.Integer(), nullable=True),
            sa.Column("task_id", sa.String(), nullable=True),
            sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["node_id", "project_id"],
                ["graph_nodes.ui_id", "graph_nodes.project_id"],
                name="fk_node_port_observations_graph_node",
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "project_id",
                "node_id",
                "port",
                name="uq_node_port_observations_project_node_port",
            ),
        )
    if not _has_index(_TABLE, _PROJECT_INDEX):
        op.create_index(_PROJECT_INDEX, _TABLE, ["project_id"], unique=False)


def downgrade() -> None:
    if _has_table(_TABLE):
        op.drop_table(_TABLE)
