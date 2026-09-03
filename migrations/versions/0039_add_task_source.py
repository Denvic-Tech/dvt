"""add task source

Revision ID: 0039
Revises: 0038
Create Date: 2026-03-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0039'
down_revision: Union[str, Sequence[str], None] = '0038'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'tasks',
        sa.Column(
            'source',
            sa.Enum('ui', 'api', 'scheduler', name='task_source', native_enum=False),
            nullable=False,
            server_default='api',
        ),
    )
    op.alter_column('tasks', 'source', server_default=None)


def downgrade() -> None:
    op.drop_column('tasks', 'source')
