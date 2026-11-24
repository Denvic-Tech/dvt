"""Add per-project Dask shuffle method.

Revision ID: 0071
Revises: 0070
Create Date: 2026-11-19 00:00:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0071"
down_revision: Union[str, Sequence[str], None] = "0070"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "projects"
_COLUMN = "shuffle_method"
_CONSTRAINT = "check_shuffle_method_allowed"


def _has_column() -> bool:
    columns = sa.inspect(op.get_bind()).get_columns(_TABLE)
    return any(item.get("name") == _COLUMN for item in columns)


def _has_constraint() -> bool:
    constraints = sa.inspect(op.get_bind()).get_check_constraints(_TABLE)
    return any(item.get("name") == _CONSTRAINT for item in constraints)


def upgrade() -> None:
    # Existing projects stay NULL ("installation default"), so their runs do not change.
    if not _has_column():
        op.add_column(_TABLE, sa.Column(_COLUMN, sa.String(), nullable=True))
    if not _has_constraint():
        op.create_check_constraint(_CONSTRAINT, _TABLE, f"{_COLUMN} IN ('disk', 'tasks')")


def downgrade() -> None:
    if _has_constraint():
        op.drop_constraint(_CONSTRAINT, _TABLE, type_="check")
    if _has_column():
        op.drop_column(_TABLE, _COLUMN)
