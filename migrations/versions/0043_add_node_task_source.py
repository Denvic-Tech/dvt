"""make task source unconstrained string

Revision ID: 0044
Revises: 0043
Create Date: 2026-03-31 16:25:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0043"
down_revision: Union[str, Sequence[str], None] = "0042"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TASK_SOURCE_CONSTRAINT_NAME = "task_source"
LEGACY_TASK_SOURCE_VALUES = ("UI", "API", "SCHEDULER")


def _fetch_non_legacy_task_sources(bind) -> list[str]:
    return [
        str(source)
        for source in bind.execute(
            sa.text(
                """
                SELECT DISTINCT source
                FROM tasks
                WHERE source IS NOT NULL
                  AND source NOT IN ('UI', 'API', 'SCHEDULER')
                ORDER BY source
                """
            )
        ).scalars().all()
    ]


def upgrade() -> None:
    op.drop_constraint(TASK_SOURCE_CONSTRAINT_NAME, "tasks", type_="check")
    op.alter_column(
        "tasks",
        "source",
        existing_nullable=False,
        type_=sa.String(),
    )


def downgrade() -> None:
    bind = op.get_bind()
    unexpected_sources = _fetch_non_legacy_task_sources(bind)
    if unexpected_sources:
        raise RuntimeError(
            "Cannot downgrade task source to constrained values. "
            "Unsupported sources found: "
            + ", ".join(unexpected_sources)
        )

    op.alter_column(
        "tasks",
        "source",
        existing_nullable=False,
        type_=sa.String(length=max(len(value) for value in LEGACY_TASK_SOURCE_VALUES)),
    )
    op.create_check_constraint(
        TASK_SOURCE_CONSTRAINT_NAME,
        "tasks",
        "source IN ('UI', 'API', 'SCHEDULER')",
    )
