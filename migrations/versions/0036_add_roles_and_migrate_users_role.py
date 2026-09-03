"""Add roles table and migrate users.is_admin to users.role.

Revision ID: 0036
Revises: 0035
Create Date: 2026-03-16 12:00:00.000000
"""

from __future__ import annotations

from typing import Any, Sequence, Union

from alembic import op
import sqlalchemy as sa
from src.enums import DVTDefaultRoles


# revision identifiers, used by Alembic.
revision: str = "0036"
down_revision: Union[str, Sequence[str], None] = "0035"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SUPERADMIN_ROLE_NAME = DVTDefaultRoles.SUPERADMIN.value
ADMIN_ROLE_NAME = DVTDefaultRoles.ADMIN.value
USER_ROLE_NAME = DVTDefaultRoles.USER.value
DEFAULT_ROLE_NAMES = DVTDefaultRoles.values()

users_table = sa.table(
    "users",
    sa.column("id", sa.String()),
    sa.column("email", sa.String(length=255)),
    sa.column("role", sa.String(length=64)),
    sa.column("is_admin", sa.Boolean()),
)

app_config_table = sa.table(
    "app_config",
    sa.column("key", sa.String()),
    sa.column("value", sa.String()),
)


def _role_name_from_is_admin(is_admin: Any) -> str:
    return ADMIN_ROLE_NAME if is_admin is True else USER_ROLE_NAME


def _is_admin_from_role_name(role_name: Any) -> bool:
    return role_name in {SUPERADMIN_ROLE_NAME, ADMIN_ROLE_NAME}


def _normalize_email(value: Any) -> str | None:
    if not isinstance(value, str):
        return None

    normalized = value.strip().lower()
    return normalized or None


def _load_user_rows_for_upgrade(bind: sa.Connection) -> list[dict[str, Any]]:
    result = bind.execute(sa.select(users_table.c.id, users_table.c.email, users_table.c.is_admin))
    return list(result.mappings())


def _load_user_rows_for_downgrade(bind: sa.Connection) -> list[dict[str, Any]]:
    result = bind.execute(sa.select(users_table.c.id, users_table.c.role))
    return list(result.mappings())


def _load_default_email(bind: sa.Connection) -> str | None:
    result = bind.execute(
        sa.select(app_config_table.c.value).where(app_config_table.c.key == "default_email")
    ).scalar_one_or_none()
    return _normalize_email(result)


def _build_user_role_updates(
    rows: list[dict[str, Any]],
    *,
    default_email: str | None = None,
) -> list[dict[str, Any]]:
    return [
        {
            "user_id": row["id"],
            "user_role": (
                SUPERADMIN_ROLE_NAME
                if default_email is not None and _normalize_email(row["email"]) == default_email
                else _role_name_from_is_admin(row["is_admin"])
            ),
        }
        for row in rows
    ]


def _build_user_admin_updates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "user_id": row["id"],
            "user_is_admin": _is_admin_from_role_name(row["role"]),
        }
        for row in rows
    ]


def _persist_user_role_updates(bind: sa.Connection, updates: list[dict[str, Any]]) -> None:
    if not updates:
        return

    statement = (
        sa.update(users_table)
        .where(users_table.c.id == sa.bindparam("user_id"))
        .values(role=sa.bindparam("user_role"))
    )
    bind.execute(statement, updates)


def _persist_user_admin_updates(bind: sa.Connection, updates: list[dict[str, Any]]) -> None:
    if not updates:
        return

    statement = (
        sa.update(users_table)
        .where(users_table.c.id == sa.bindparam("user_id"))
        .values(is_admin=sa.bindparam("user_is_admin"))
    )
    bind.execute(statement, updates)


def upgrade() -> None:
    bind = op.get_bind()

    op.add_column("users", sa.Column("role", sa.String(length=64), nullable=True))

    upgrade_rows = _load_user_rows_for_upgrade(bind)
    default_email = _load_default_email(bind)
    _persist_user_role_updates(
        bind,
        _build_user_role_updates(upgrade_rows, default_email=default_email),
    )

    op.alter_column("users", "role", existing_type=sa.String(length=64), nullable=False)
    op.create_index(op.f("ix_users_role"), "users", ["role"], unique=False)
    op.drop_column("users", "is_admin")


def downgrade() -> None:
    op.add_column("users", sa.Column("is_admin", sa.Boolean(), nullable=True))

    bind = op.get_bind()
    downgrade_rows = _load_user_rows_for_downgrade(bind)
    _persist_user_admin_updates(bind, _build_user_admin_updates(downgrade_rows))

    op.alter_column("users", "is_admin", existing_type=sa.Boolean(), nullable=False)
    op.drop_index(op.f("ix_users_role"), table_name="users")
    op.drop_column("users", "role")
