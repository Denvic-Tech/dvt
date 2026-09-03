"""Migrate env vars to app_config values.

Revision ID: 0035
Revises: 0034
Create Date: 2026-03-10 18:10:00.000000
"""

from __future__ import annotations

import os
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0035"
down_revision: Union[str, Sequence[str], None] = "0034"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


APP_CONFIG_TABLE = sa.table(
    "app_config",
    sa.column("key", sa.String()),
    sa.column("value", sa.String()),
)

ENV_TO_CONFIG_KEYS: dict[str, str] = {
    "LICENSE_KEY": "license_key",
    "DEFAULT_EMAIL": "default_email",
    "DEFAULT_PASSWORD": "default_password",
}


def _collect_env_values() -> dict[str, str]:
    values: dict[str, str] = {}
    for env_key, config_key in ENV_TO_CONFIG_KEYS.items():
        env_value = os.getenv(env_key)
        if env_value is None:
            continue
        values[config_key] = env_value
    return values


def _load_existing_values(bind: sa.Connection, keys: tuple[str, ...]) -> dict[str, str | None]:
    statement = sa.select(APP_CONFIG_TABLE.c.key, APP_CONFIG_TABLE.c.value).where(
        APP_CONFIG_TABLE.c.key.in_(keys)
    )
    result = bind.execute(statement)
    return {row["key"]: row["value"] for row in result.mappings()}


def _insert_missing_keys(bind: sa.Connection, values: dict[str, str], existing: dict[str, str | None]) -> None:
    rows_to_insert = [
        {"key": key, "value": value}
        for key, value in values.items()
        if key not in existing
    ]

    if rows_to_insert:
        bind.execute(sa.insert(APP_CONFIG_TABLE), rows_to_insert)


def _update_null_values(bind: sa.Connection, values: dict[str, str], existing: dict[str, str | None]) -> None:
    rows_to_update = [
        {"row_key": key, "row_value": values[key]}
        for key, current_value in existing.items()
        if current_value is None
    ]

    if not rows_to_update:
        return

    statement = (
        sa.update(APP_CONFIG_TABLE)
        .where(APP_CONFIG_TABLE.c.key == sa.bindparam("row_key"))
        .where(APP_CONFIG_TABLE.c.value.is_(None))
        .values(value=sa.bindparam("row_value"))
    )
    bind.execute(statement, rows_to_update)


def upgrade() -> None:
    bind = op.get_bind()
    env_values = _collect_env_values()

    if not env_values:
        return

    existing_values = _load_existing_values(bind, tuple(env_values.keys()))
    _insert_missing_keys(bind, env_values, existing_values)
    _update_null_values(bind, env_values, existing_values)


def downgrade() -> None:
    # Значения пришли из окружения и могут быть изменены после миграции,
    # поэтому безопасного обратного преобразования нет.
    pass
