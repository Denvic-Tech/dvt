"""add task termination reason

Revision ID: 0042
Revises: 0041
Create Date: 2026-03-26 16:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0042'
down_revision: Union[str, Sequence[str], None] = '0041'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('tasks', sa.Column('termination_reason', sa.String(), nullable=True))
    op.create_index(
        'ix_tasks_status_updated_at',
        'tasks',
        ['status', 'updated_at'],
        unique=False
    )


def downgrade() -> None:
    op.drop_index('ix_tasks_status_updated_at', table_name='tasks')
    op.drop_column('tasks', 'termination_reason')
