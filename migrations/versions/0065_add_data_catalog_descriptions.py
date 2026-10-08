"""ADD data catalog description attribution, run observation and last check error columns

Revision ID: 0065
Revises: 0064
Create Date: 2026-10-08 00:00:00.000000

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


def _columns() -> tuple[tuple[str, sa.Column], ...]:
    return (
        ("datasets", sa.Column("description_updated_by", sa.String(), nullable=True)),
        ("datasets", sa.Column("description_updated_at", sa.DateTime(timezone=True), nullable=True)),
        ("datasets", sa.Column("observed_at_run", sa.DateTime(timezone=True), nullable=True)),
        ("datasets", sa.Column("last_check_error", sa.Text(), nullable=True)),
        ("datasets", sa.Column("last_check_error_kind", sa.String(length=32), nullable=True)),
        ("dataset_fields", sa.Column("description_updated_by", sa.String(), nullable=True)),
        ("dataset_fields", sa.Column("description_updated_at", sa.DateTime(timezone=True), nullable=True)),
    )


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def _has_column(table: str, column: str) -> bool:
    columns = sa.inspect(op.get_bind()).get_columns(table)
    return any(item.get("name") == column for item in columns)


def upgrade() -> None:
    for table, column in _columns():
        if not _has_table(table) or _has_column(table, column.name):
            continue
        op.add_column(table, column)


def downgrade() -> None:
    by_table: dict[str, list[str]] = {}
    for table, column in _columns():
        by_table.setdefault(table, []).append(column.name)

    for table, names in by_table.items():
        if not _has_table(table):
            continue
        present = [name for name in names if _has_column(table, name)]
        if not present:
            continue
        # batch_alter_table нужен SQLite; на PostgreSQL сводится к обычному ALTER TABLE.
        with op.batch_alter_table(table) as batch:
            for name in present:
                batch.drop_column(name)
