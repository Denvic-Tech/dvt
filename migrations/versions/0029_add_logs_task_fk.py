"""ADD FK logs.task_id -> tasks.task_id

Revision ID: 0029
Revises: 0028
Create Date: 2026-02-20 15:45:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0029"
down_revision: Union[str, Sequence[str], None] = "0028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullify orphan task references to avoid migration failure on existing data.
    op.execute(
        sa.text(
            """
            UPDATE logs
            SET task_id = NULL
            WHERE task_id IS NOT NULL
              AND NOT EXISTS (
                SELECT 1
                FROM tasks
                WHERE tasks.task_id = logs.task_id
            )
            """
        )
    )

    op.create_foreign_key(
        "logs_task_id_fkey",
        "logs",
        "tasks",
        ["task_id"],
        ["task_id"],
    )


def downgrade() -> None:
    op.drop_constraint("logs_task_id_fkey", "logs", type_="foreignkey")
