"""Rename legacy graph input handles and node input keys.

Revision ID: 0028
Revises: 0027
Create Date: 2026-02-19 16:22:43.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0028"
down_revision: Union[str, Sequence[str], None] = "0027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE graph_edges
            SET target_handle = CASE target_handle
                WHEN 'input-dataframe' THEN 'input-df'
                WHEN 'include_index' THEN 'index'
                WHEN 'include_header' THEN 'header'
                ELSE target_handle
            END
            WHERE target_handle IN ('input-dataframe', 'include_index', 'include_header')
            """
        )
    )

    op.execute(
        sa.text(
            """
            UPDATE graph_nodes AS gn
            SET input_values = (
                (gn.input_values - 'dataframe' - 'include_index' - 'include_header')
                || CASE
                    WHEN gn.input_values ? 'dataframe' AND NOT (gn.input_values ? 'df')
                    THEN jsonb_build_object('df', gn.input_values -> 'dataframe')
                    ELSE '{}'::jsonb
                END
                || CASE
                    WHEN gn.input_values ? 'include_index' AND NOT (gn.input_values ? 'index')
                    THEN jsonb_build_object('index', gn.input_values -> 'include_index')
                    ELSE '{}'::jsonb
                END
                || CASE
                    WHEN gn.input_values ? 'include_header' AND NOT (gn.input_values ? 'header')
                    THEN jsonb_build_object('header', gn.input_values -> 'include_header')
                    ELSE '{}'::jsonb
                END
            )
            WHERE gn.input_values IS NOT NULL
              AND jsonb_typeof(gn.input_values) = 'object'
              AND gn.input_values ?| array['dataframe', 'include_index', 'include_header']
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE graph_edges
            SET target_handle = CASE target_handle
                WHEN 'input-df' THEN 'input-dataframe'
                WHEN 'index' THEN 'include_index'
                WHEN 'header' THEN 'include_header'
                ELSE target_handle
            END
            WHERE target_handle IN ('input-df', 'index', 'header')
            """
        )
    )

    op.execute(
        sa.text(
            """
            UPDATE graph_nodes AS gn
            SET input_values = (
                (gn.input_values - 'df' - 'index' - 'header')
                || CASE
                    WHEN gn.input_values ? 'df' AND NOT (gn.input_values ? 'dataframe')
                    THEN jsonb_build_object('dataframe', gn.input_values -> 'df')
                    ELSE '{}'::jsonb
                END
                || CASE
                    WHEN gn.input_values ? 'index' AND NOT (gn.input_values ? 'include_index')
                    THEN jsonb_build_object('include_index', gn.input_values -> 'index')
                    ELSE '{}'::jsonb
                END
                || CASE
                    WHEN gn.input_values ? 'header' AND NOT (gn.input_values ? 'include_header')
                    THEN jsonb_build_object('include_header', gn.input_values -> 'header')
                    ELSE '{}'::jsonb
                END
            )
            WHERE gn.input_values IS NOT NULL
              AND jsonb_typeof(gn.input_values) = 'object'
              AND gn.input_values ?| array['df', 'index', 'header']
            """
        )
    )
