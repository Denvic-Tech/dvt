"""Persist extension catalog release metadata."""

import sqlalchemy as sa
from alembic import op

revision = "0069"
down_revision = "0068"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("extensions", sa.Column("catalog_releases", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("extensions", "catalog_releases")
