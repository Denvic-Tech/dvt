"""Persist the task admission gate and preparation proof for child executions."""

import sqlalchemy as sa
from alembic import op

revision = "0070"
down_revision = "0069"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "task_admission_control",
        sa.Column("singleton", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("operation_id", sa.Uuid(), nullable=True),
        sa.Column("frozen", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.CheckConstraint("singleton = 1", name="ck_task_admission_singleton"),
        sa.CheckConstraint("NOT frozen OR operation_id IS NOT NULL", name="ck_task_admission_frozen"),
        if_not_exists=True,
    )
    op.execute("INSERT INTO task_admission_control (singleton) VALUES (1) ON CONFLICT DO NOTHING")
    # A historical parent ID stays valid even if task history is later pruned.
    op.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS prepared_by_parent_id VARCHAR")
    op.execute(
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS maintenance_worker_lost "
        "BOOLEAN NOT NULL DEFAULT FALSE"
    )


def downgrade() -> None:
    # Previous binaries ignore these additive fields. Retaining the gate and any closed operation
    # also keeps an upgrade from accidentally reopening admission after a revision-only downgrade.
    # The next upgrade reuses these structures; legacy binaries do not support maintenance.
    pass
