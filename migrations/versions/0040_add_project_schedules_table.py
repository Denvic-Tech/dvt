"""add project schedules table

Revision ID: 0040
Revises: 0039
Create Date: 2026-03-24 00:00:00.000000

"""
from datetime import datetime, timezone
from typing import Sequence, Union
from uuid import uuid4

from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision: str = "0040"
down_revision: Union[str, Sequence[str], None] = "0039"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "project_schedules",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("project_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("scheduled_by_user_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("cron", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("disabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["scheduled_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id"),
    )
    op.create_index(op.f("ix_project_schedules_project_id"), "project_schedules", ["project_id"], unique=False)
    op.create_index(
        op.f("ix_project_schedules_scheduled_by_user_id"),
        "project_schedules",
        ["scheduled_by_user_id"],
        unique=False,
    )

    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            """
            SELECT id, crontab
            FROM projects
            WHERE crontab IS NOT NULL AND btrim(crontab) <> ''
            """
        )
    ).mappings()
    now = datetime.now(tz=timezone.utc)
    for row in rows:
        connection.execute(
            sa.text(
                """
                INSERT INTO project_schedules
                    (created_at, updated_at, id, project_id, scheduled_by_user_id, cron, disabled)
                VALUES
                    (:created_at, :updated_at, :id, :project_id, :scheduled_by_user_id, :cron, :disabled)
                """
            ),
            {
                "created_at": now,
                "updated_at": now,
                "id": str(uuid4()),
                "project_id": row["id"],
                "scheduled_by_user_id": None,
                "cron": row["crontab"],
                "disabled": False,
            },
        )

    op.drop_column("projects", "crontab")


def downgrade() -> None:
    op.add_column("projects", sa.Column("crontab", sqlmodel.sql.sqltypes.AutoString(), nullable=True))

    op.execute(
        """
        UPDATE projects
        SET crontab = ps.cron
        FROM project_schedules ps
        WHERE ps.project_id = projects.id
          AND ps.disabled = FALSE
        """
    )

    op.drop_index(op.f("ix_project_schedules_scheduled_by_user_id"), table_name="project_schedules")
    op.drop_index(op.f("ix_project_schedules_project_id"), table_name="project_schedules")
    op.drop_table("project_schedules")
