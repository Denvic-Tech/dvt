"""add extensions tables

Revision ID: 0038
Revises: 0037
Create Date: 2026-03-10 12:55:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes

# revision identifiers, used by Alembic.
revision: str = '0038'
down_revision: Union[str, Sequence[str], None] = '0037'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'extensions',
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('display_name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('description', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('repository_url', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('is_enabled', sa.Boolean(), nullable=False),
        sa.Column('is_installed', sa.Boolean(), nullable=False),
        sa.Column('current_version', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('last_version', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('install_path', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('manifest_json', sa.JSON(), nullable=False),
        sa.Column('state_json', sa.JSON(), nullable=False),
        sa.Column('error_message', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('installed_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_extensions_name'), 'extensions', ['name'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_extensions_name'), table_name='extensions')
    op.drop_table('extensions')
