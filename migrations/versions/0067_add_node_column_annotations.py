"""ADD node column annotations table

Revision ID: 0067
Revises: 0066
Create Date: 2026-10-21 00:00:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0067"
down_revision: Union[str, Sequence[str], None] = "0066"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "node_column_annotations"
_PROJECT_INDEX = "ix_node_column_annotations_project_id"


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def _has_index(table: str, index: str) -> bool:
    indexes = sa.inspect(op.get_bind()).get_indexes(table)
    return any(item.get("name") == index for item in indexes)


def upgrade() -> None:
    if not _has_table(_TABLE):
        # Описание колонки порта ноды живёт вместе с нодой: составной FK на (ui_id, project_id)
        # удаляет строки при удалении ноды, очистке графа при импорте и удалении проекта.
        op.create_table(
            _TABLE,
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("project_id", sa.String(), nullable=False),
            sa.Column("node_id", sa.String(), nullable=False),
            sa.Column("port", sa.String(length=128), nullable=False),
            sa.Column("column_name", sa.String(length=512), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("origin_key", sa.Text(), nullable=True),
            sa.Column("description_updated_by", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["node_id", "project_id"],
                ["graph_nodes.ui_id", "graph_nodes.project_id"],
                name="fk_node_column_annotations_graph_node",
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "project_id",
                "node_id",
                "port",
                "column_name",
                name="uq_node_column_annotations_project_node_port_column",
            ),
        )
    if not _has_index(_TABLE, _PROJECT_INDEX):
        op.create_index(_PROJECT_INDEX, _TABLE, ["project_id"], unique=False)


def downgrade() -> None:
    if _has_table(_TABLE):
        op.drop_table(_TABLE)
