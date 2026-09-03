"""Fix extension timestamps and FK reverted by 0052 autogenerate

Revision ID: 0053
Revises: 0052
Create Date: 2026-05-26 16:00:00.000000

Migration 0052 (auto-generated) contained unwanted schema changes alongside
the intended available_versions column. This migration reverts those changes:
- Restore TIMESTAMP WITH TIME ZONE for license_activated_at / license_expires_at
- Recreate ix_extensions_license_status index if dropped
- Restore fk_projects_folder with ON DELETE SET NULL

All operations are idempotent — safe whether 0052 was applied or not.

"""

from typing import Sequence, Union

from alembic import op

revision: str = "0053"
down_revision: Union[str, Sequence[str], None] = "0052"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Restore timezone-aware timestamps reverted by 0052
    op.execute(
        "ALTER TABLE extensions ALTER COLUMN license_activated_at "
        "TYPE TIMESTAMP WITH TIME ZONE"
    )
    op.execute(
        "ALTER TABLE extensions ALTER COLUMN license_expires_at "
        "TYPE TIMESTAMP WITH TIME ZONE"
    )

    # Recreate index dropped by 0052
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_extensions_license_status "
        "ON extensions (license_status)"
    )

    # Restore FK with ON DELETE SET NULL. 0052 dropped the named constraint
    # and created an unnamed one without ON DELETE. Drop whatever FK exists
    # and recreate with the original definition from migration 0048.
    op.execute(
        """
        DO $$
        DECLARE
            fk_name text;
        BEGIN
            SELECT conname INTO fk_name
            FROM pg_constraint
            WHERE conrelid = 'projects'::regclass
              AND confrelid = 'project_folders'::regclass
              AND contype = 'f';

            IF fk_name IS NOT NULL THEN
                EXECUTE 'ALTER TABLE projects DROP CONSTRAINT ' || fk_name;
            END IF;
        END $$;
        """
    )
    op.create_foreign_key(
        "fk_projects_folder",
        "projects",
        "project_folders",
        ["folder_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    # No-op: we don't revert the fixes back to the broken state
    pass
