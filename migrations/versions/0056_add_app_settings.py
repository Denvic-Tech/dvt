"""Add app settings bounded context tables.

Revision ID: 0056
Revises: 0055
Create Date: 2026-07-29 00:00:00.000000
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Sequence, Union
from uuid import uuid4

from alembic import op
from cryptography.fernet import Fernet, InvalidToken
import sqlalchemy as sa


revision: str = "0056"
down_revision: Union[str, Sequence[str], None] = "0055"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SECRET_KEYS = {"license.key", "dcc.password"}

OLD_TO_NEW_KEYS = {
    "id_connector": "dcc.connector_id",
    "dcc_url": "dcc.url",
    "dcc_user": "dcc.username",
    "dcc_password": "dcc.password",
    "license_key": "license.key",
    "oom_guard_settings": "runtime.oom_guard",
}

NEW_TO_OLD_KEYS = {value: key for key, value in OLD_TO_NEW_KEYS.items()}

old_app_config = sa.table(
    "app_config",
    sa.column("key", sa.String()),
    sa.column("value", sa.String()),
)
app_setting_values = sa.table(
    "app_setting_values",
    sa.column("id", sa.String()),
    sa.column("key", sa.String()),
    sa.column("value", sa.Text()),
    sa.column("version", sa.Integer()),
    sa.column("updated_at", sa.DateTime(timezone=True)),
    sa.column("updated_by", sa.String()),
)
app_setting_changes = sa.table(
    "app_setting_changes",
    sa.column("id", sa.String()),
    sa.column("key", sa.String()),
    sa.column("old_value", sa.Text()),
    sa.column("new_value", sa.Text()),
    sa.column("changed_at", sa.DateTime(timezone=True)),
    sa.column("changed_by", sa.String()),
    sa.column("change_reason", sa.Text()),
)


def _get_fernet(secret_values_present: bool) -> Fernet | None:
    from config import SECURITY

    key = SECURITY.FERNET_KEY
    if not key and secret_values_present:
        raise RuntimeError("FERNET_KEY is required to migrate app settings secrets.")
    return Fernet(key.encode("utf-8")) if key else None


def _serialize(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        json.loads(value)
        return value
    except json.JSONDecodeError:
        return json.dumps(value, ensure_ascii=False)


def _encrypt(value: str | None, *, key: str, fernet: Fernet | None) -> str | None:
    if value is None or key not in SECRET_KEYS:
        return value
    if fernet is None:
        raise RuntimeError("FERNET_KEY is required to migrate app settings secrets.")
    return fernet.encrypt(value.encode("utf-8")).decode("utf-8")


def _decrypt(value: str | None, *, key: str, fernet: Fernet | None) -> str | None:
    if value is None or key not in SECRET_KEYS:
        return value
    if fernet is None:
        raise RuntimeError("FERNET_KEY is required to downgrade app settings secrets.")
    try:
        return fernet.decrypt(value.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise RuntimeError(f"Could not decrypt app setting '{key}'.") from exc


def upgrade() -> None:
    op.create_table(
        "app_setting_values",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
    )
    op.create_index(op.f("ix_app_setting_values_key"), "app_setting_values", ["key"])

    op.create_table(
        "app_setting_changes",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("changed_by", sa.String(length=255), nullable=True),
        sa.Column("change_reason", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_app_setting_changes_key"), "app_setting_changes", ["key"])
    op.create_index(op.f("ix_app_setting_changes_changed_at"), "app_setting_changes", ["changed_at"])

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "app_config" not in inspector.get_table_names():
        return

    rows = list(
        bind.execute(
            sa.select(old_app_config.c.key, old_app_config.c.value).where(
                old_app_config.c.key.in_(tuple(OLD_TO_NEW_KEYS))
            )
        ).mappings()
    )
    secret_values_present = any(
        OLD_TO_NEW_KEYS[row["key"]] in SECRET_KEYS and row["value"] is not None
        for row in rows
    )
    fernet = _get_fernet(secret_values_present)
    now = datetime.now(UTC)

    values_to_insert = []
    changes_to_insert = []
    for row in rows:
        new_key = OLD_TO_NEW_KEYS[row["key"]]
        serialized = _serialize(row["value"])
        stored = _encrypt(serialized, key=new_key, fernet=fernet)
        values_to_insert.append(
            {
                "id": str(uuid4()),
                "key": new_key,
                "value": stored,
                "version": 1,
                "updated_at": now,
                "updated_by": "migration:0056",
            }
        )
        changes_to_insert.append(
            {
                "id": str(uuid4()),
                "key": new_key,
                "old_value": None,
                "new_value": stored,
                "changed_at": now,
                "changed_by": "migration:0056",
                "change_reason": "Migrate app_config to app_settings",
            }
        )

    if values_to_insert:
        bind.execute(sa.insert(app_setting_values), values_to_insert)
        bind.execute(sa.insert(app_setting_changes), changes_to_insert)

    op.drop_table("app_config")


def downgrade() -> None:
    op.create_table(
        "app_config",
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("value", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("key"),
    )

    bind = op.get_bind()
    rows = list(
        bind.execute(
            sa.select(app_setting_values.c.key, app_setting_values.c.value).where(
                app_setting_values.c.key.in_(tuple(NEW_TO_OLD_KEYS))
            )
        ).mappings()
    )
    secret_values_present = any(row["key"] in SECRET_KEYS and row["value"] is not None for row in rows)
    fernet = _get_fernet(secret_values_present)

    old_rows = []
    for row in rows:
        payload = _decrypt(row["value"], key=row["key"], fernet=fernet)
        if payload is not None:
            try:
                value = json.loads(payload)
            except json.JSONDecodeError:
                value = payload
            if not isinstance(value, str):
                value = json.dumps(value, ensure_ascii=False)
        else:
            value = None
        old_rows.append({"key": NEW_TO_OLD_KEYS[row["key"]], "value": value})

    if old_rows:
        bind.execute(sa.insert(old_app_config), old_rows)

    op.drop_index(op.f("ix_app_setting_changes_changed_at"), table_name="app_setting_changes")
    op.drop_index(op.f("ix_app_setting_changes_key"), table_name="app_setting_changes")
    op.drop_table("app_setting_changes")
    op.drop_index(op.f("ix_app_setting_values_key"), table_name="app_setting_values")
    op.drop_table("app_setting_values")
