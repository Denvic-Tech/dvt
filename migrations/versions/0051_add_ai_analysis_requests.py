"""add ai analysis requests

Revision ID: 0051
Revises: 0050
Create Date: 2026-05-21 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision: str = "0051"
down_revision: Union[str, Sequence[str], None] = "0050"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ai_analysis_requests",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("task_id", sa.String(), nullable=False),
        sa.Column("ai_service_request_id", sa.String(), nullable=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("organization_id", sa.String(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "queued",
                "running",
                "success",
                "error",
                name="ai_analysis_status",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=40), nullable=True),
        sa.Column("context", sa.JSON(), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_ai_analysis_requests_ai_service_request_id"),
        "ai_analysis_requests",
        ["ai_service_request_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ai_analysis_requests_organization_id"),
        "ai_analysis_requests",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ai_analysis_requests_project_id"),
        "ai_analysis_requests",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ai_analysis_requests_task_id"),
        "ai_analysis_requests",
        ["task_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ai_analysis_requests_user_id"),
        "ai_analysis_requests",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_ai_analysis_requests_project_user_status_created",
        "ai_analysis_requests",
        ["project_id", "user_id", "status", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_ai_analysis_requests_org_status_created",
        "ai_analysis_requests",
        ["organization_id", "status", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_ai_analysis_requests_project_created",
        "ai_analysis_requests",
        ["project_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_ai_analysis_requests_project_created", table_name="ai_analysis_requests")
    op.drop_index("ix_ai_analysis_requests_org_status_created", table_name="ai_analysis_requests")
    op.drop_index(
        "ix_ai_analysis_requests_project_user_status_created",
        table_name="ai_analysis_requests",
    )
    op.drop_index(
        op.f("ix_ai_analysis_requests_ai_service_request_id"),
        table_name="ai_analysis_requests",
    )
    op.drop_index(op.f("ix_ai_analysis_requests_task_id"), table_name="ai_analysis_requests")
    op.drop_index(op.f("ix_ai_analysis_requests_user_id"), table_name="ai_analysis_requests")
    op.drop_index(op.f("ix_ai_analysis_requests_project_id"), table_name="ai_analysis_requests")
    op.drop_index(
        op.f("ix_ai_analysis_requests_organization_id"),
        table_name="ai_analysis_requests",
    )
    op.drop_table("ai_analysis_requests")
