from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_module():
    module_path = (
        Path(__file__).resolve().parents[4]
        / "migrations"
        / "versions"
        / "0036_add_roles_and_migrate_users_role.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0036", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to load migration module 0036")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_user_role_updates_maps_is_admin_to_default_roles() -> None:
    migration = _load_module()

    rows = [
        {"id": "u-admin", "email": "admin@example.com", "is_admin": True},
        {"id": "u-user", "email": "user@example.com", "is_admin": False},
        {"id": "u-null", "email": None, "is_admin": None},
    ]

    updates = migration._build_user_role_updates(rows)

    assert updates == [
        {"user_id": "u-admin", "user_role": migration.ADMIN_ROLE_NAME},
        {"user_id": "u-user", "user_role": migration.USER_ROLE_NAME},
        {"user_id": "u-null", "user_role": migration.USER_ROLE_NAME},
    ]


def test_build_user_role_updates_promotes_default_email_to_superadmin() -> None:
    migration = _load_module()

    rows = [
        {"id": "u-default", "email": "  Default@Example.com ", "is_admin": False},
        {"id": "u-admin", "email": "admin@example.com", "is_admin": True},
    ]

    updates = migration._build_user_role_updates(
        rows,
        default_email="default@example.com",
    )

    assert updates == [
        {"user_id": "u-default", "user_role": migration.SUPERADMIN_ROLE_NAME},
        {"user_id": "u-admin", "user_role": migration.ADMIN_ROLE_NAME},
    ]


def test_build_user_admin_updates_maps_admin_and_superadmin_roles_back_to_boolean() -> None:
    migration = _load_module()

    rows = [
        {"id": "u-superadmin", "role": migration.SUPERADMIN_ROLE_NAME},
        {"id": "u-admin", "role": migration.ADMIN_ROLE_NAME},
        {"id": "u-user", "role": migration.USER_ROLE_NAME},
        {"id": "u-custom", "role": "support"},
        {"id": "u-null", "role": None},
    ]

    updates = migration._build_user_admin_updates(rows)

    assert updates == [
        {"user_id": "u-superadmin", "user_is_admin": True},
        {"user_id": "u-admin", "user_is_admin": True},
        {"user_id": "u-user", "user_is_admin": False},
        {"user_id": "u-custom", "user_is_admin": False},
        {"user_id": "u-null", "user_is_admin": False},
    ]
