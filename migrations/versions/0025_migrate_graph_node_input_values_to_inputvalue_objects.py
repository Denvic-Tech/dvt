"""Migrate graph_nodes.input_values to InputValue objects

Revision ID: 0025
Revises: 0024
Create Date: 2026-02-09 18:48:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0025"
down_revision: Union[str, Sequence[str], None] = "0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Wrap legacy input_values entries into InputConstantValue objects.

    Only non-converted entries are transformed.
    Converted entries are JSON objects with __dvt_type in {"var", "const"}.
    """
    op.execute(
        sa.text(
            """
            UPDATE graph_nodes AS gn
            SET input_values = (
                SELECT jsonb_object_agg(
                    e.key,
                    CASE
                        WHEN jsonb_typeof(e.value) = 'object'
                             AND e.value ? '__dvt_type'
                             AND (e.value ->> '__dvt_type') IN ('var', 'const')
                        THEN e.value
                        ELSE jsonb_build_object('__dvt_type', 'const', 'value', e.value)
                    END
                )
                FROM jsonb_each(gn.input_values) AS e(key, value)
            )
            WHERE gn.input_values IS NOT NULL
              AND jsonb_typeof(gn.input_values) = 'object'
              AND EXISTS (
                    SELECT 1
                    FROM jsonb_each(gn.input_values) AS e2(key, value)
                    WHERE NOT (
                        jsonb_typeof(e2.value) = 'object'
                        AND e2.value ? '__dvt_type'
                        AND (e2.value ->> '__dvt_type') IN ('var', 'const')
                    )
              )
            """
        )
    )


def downgrade() -> None:
    """Unwrap only InputConstantValue-like entries back to raw values.

    For entries with {"__dvt_type": "const", ...}:
    - prefer "value"
    - fallback to "value"
    Other entries (including "__dvt_type": "var") are preserved as-is.
    """
    op.execute(
        sa.text(
            """
            UPDATE graph_nodes AS gn
            SET input_values = (
                SELECT jsonb_object_agg(
                    e.key,
                    CASE
                        WHEN jsonb_typeof(e.value) = 'object'
                             AND e.value ? '__dvt_type'
                             AND e.value ->> '__dvt_type' = 'const'
                        THEN COALESCE(e.value -> 'value', e.value)
                        ELSE e.value
                    END
                )
                FROM jsonb_each(gn.input_values) AS e(key, value)
            )
            WHERE gn.input_values IS NOT NULL
              AND jsonb_typeof(gn.input_values) = 'object'
              AND EXISTS (
                    SELECT 1
                    FROM jsonb_each(gn.input_values) AS e2(key, value)
                    WHERE jsonb_typeof(e2.value) = 'object'
                      AND e2.value ? '__dvt_type'
                      AND e2.value ->> '__dvt_type' = 'const'
              )
            """
        )
    )
