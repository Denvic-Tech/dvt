"""Add durable project schedule retry chains.

Revision ID: 0058
Revises: 0057
Create Date: 2026-08-10 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


revision: str = "0058"
down_revision: Union[str, Sequence[str], None] = "0057"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "project_schedules",
        sa.Column("mode", sa.String(), server_default="FULL", nullable=False),
    )
    op.add_column(
        "project_schedules",
        sa.Column("force_exec", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "project_schedules",
        sa.Column("max_retries", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "project_schedules",
        sa.Column("retry_delay_seconds", sa.Integer(), server_default="60", nullable=False),
    )
    op.add_column(
        "project_schedules",
        sa.Column("retry_backoff", sa.String(), server_default="FIXED", nullable=False),
    )
    op.add_column(
        "project_schedules",
        sa.Column("retry_max_delay_seconds", sa.Integer(), server_default="3600", nullable=False),
    )
    op.create_check_constraint(
        "check_project_schedules_max_retries",
        "project_schedules",
        "max_retries BETWEEN 0 AND 10",
    )
    op.create_check_constraint(
        "check_project_schedules_retry_delay",
        "project_schedules",
        "retry_delay_seconds BETWEEN 1 AND 86400",
    )
    op.create_check_constraint(
        "check_project_schedules_retry_max_delay",
        "project_schedules",
        "retry_max_delay_seconds BETWEEN 1 AND 86400",
    )

    op.create_table(
        "project_schedule_runs",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("schedule_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), server_default="PENDING", nullable=False),
        sa.Column("scheduled_at", sa.DateTime(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), server_default="0", nullable=False),
        sa.Column("attempt_started_at", sa.DateTime(), nullable=True),
        sa.Column("current_task_id", sa.String(), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.String(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("max_retries", sa.Integer(), nullable=False),
        sa.Column("retry_delay_seconds", sa.Integer(), nullable=False),
        sa.Column("retry_backoff", sa.String(), nullable=False),
        sa.Column("retry_max_delay_seconds", sa.Integer(), nullable=False),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("force_exec", sa.Boolean(), nullable=False),
        sa.Column("scheduled_by_user_id", sa.String(), nullable=True),
        sa.CheckConstraint("attempt_number >= 0", name="check_project_schedule_runs_attempt"),
        sa.CheckConstraint("max_retries BETWEEN 0 AND 10", name="check_project_schedule_runs_max_retries"),
        sa.CheckConstraint(
            "retry_delay_seconds BETWEEN 1 AND 86400",
            name="check_project_schedule_runs_retry_delay",
        ),
        sa.CheckConstraint(
            "retry_max_delay_seconds BETWEEN 1 AND 86400",
            name="check_project_schedule_runs_retry_max_delay",
        ),
        sa.ForeignKeyConstraint(
            ["schedule_id"],
            ["project_schedules.id"],
            name="fk_project_schedule_runs_schedule_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_project_schedule_runs_schedule_id",
        "project_schedule_runs",
        ["schedule_id"],
    )
    op.create_index(
        "ix_project_schedule_runs_current_task_id",
        "project_schedule_runs",
        ["current_task_id"],
    )
    op.create_index(
        "ix_project_schedule_runs_next_retry_at",
        "project_schedule_runs",
        ["next_retry_at"],
    )
    op.create_index(
        "ix_project_schedule_runs_reconcile",
        "project_schedule_runs",
        ["status", "next_retry_at"],
    )
    op.create_index(
        "uq_project_schedule_runs_active_schedule",
        "project_schedule_runs",
        ["schedule_id"],
        unique=True,
        postgresql_where=sa.text("finished_at IS NULL"),
        sqlite_where=sa.text("finished_at IS NULL"),
    )

    op.add_column("tasks", sa.Column("schedule_run_id", sa.String(), nullable=True))
    op.add_column("tasks", sa.Column("schedule_attempt", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_tasks_schedule_run_id",
        "tasks",
        "project_schedule_runs",
        ["schedule_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "check_tasks_schedule_attempt_positive",
        "tasks",
        "schedule_attempt IS NULL OR schedule_attempt >= 1",
    )
    op.create_unique_constraint(
        "uq_tasks_schedule_run_attempt",
        "tasks",
        ["schedule_run_id", "schedule_attempt"],
    )
    op.create_index("ix_tasks_schedule_run_id", "tasks", ["schedule_run_id"])


def downgrade() -> None:
    op.drop_index("ix_tasks_schedule_run_id", table_name="tasks")
    op.drop_constraint("uq_tasks_schedule_run_attempt", "tasks", type_="unique")
    op.drop_constraint("check_tasks_schedule_attempt_positive", "tasks", type_="check")
    op.drop_constraint("fk_tasks_schedule_run_id", "tasks", type_="foreignkey")
    op.drop_column("tasks", "schedule_attempt")
    op.drop_column("tasks", "schedule_run_id")

    op.drop_index("uq_project_schedule_runs_active_schedule", table_name="project_schedule_runs")
    op.drop_index("ix_project_schedule_runs_reconcile", table_name="project_schedule_runs")
    op.drop_index("ix_project_schedule_runs_next_retry_at", table_name="project_schedule_runs")
    op.drop_index("ix_project_schedule_runs_current_task_id", table_name="project_schedule_runs")
    op.drop_index("ix_project_schedule_runs_schedule_id", table_name="project_schedule_runs")
    op.drop_table("project_schedule_runs")

    op.drop_constraint("check_project_schedules_retry_max_delay", "project_schedules", type_="check")
    op.drop_constraint("check_project_schedules_retry_delay", "project_schedules", type_="check")
    op.drop_constraint("check_project_schedules_max_retries", "project_schedules", type_="check")
    op.drop_column("project_schedules", "retry_max_delay_seconds")
    op.drop_column("project_schedules", "retry_backoff")
    op.drop_column("project_schedules", "retry_delay_seconds")
    op.drop_column("project_schedules", "max_retries")
    op.drop_column("project_schedules", "force_exec")
    op.drop_column("project_schedules", "mode")
