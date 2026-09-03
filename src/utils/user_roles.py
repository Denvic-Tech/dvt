from __future__ import annotations

from enum import Enum
from typing import Any

from src.enums import DVTDefaultRoles


PRIVILEGED_ROLE_VALUES = frozenset(
    {
        DVTDefaultRoles.SUPERADMIN.value,
        DVTDefaultRoles.ADMIN.value,
    }
)
GLOBAL_ROLE_VALUES = frozenset({DVTDefaultRoles.SUPERADMIN.value})
SUPERADMIN_ROLE_VALUES = frozenset({DVTDefaultRoles.SUPERADMIN.value})


def normalize_user_role(role: Any) -> str | None:
    if isinstance(role, Enum):
        role = role.value

    if not isinstance(role, str):
        return None

    normalized = role.strip().lower()
    return normalized or None


def role_has_admin_access(role: Any) -> bool:
    return normalize_user_role(role) in PRIVILEGED_ROLE_VALUES


def user_has_admin_access(user: Any) -> bool:
    return role_has_admin_access(getattr(user, "role", None))


def role_has_global_access(role: Any) -> bool:
    return normalize_user_role(role) in GLOBAL_ROLE_VALUES


def user_has_global_access(user: Any) -> bool:
    return role_has_global_access(getattr(user, "role", None))


def role_is_superadmin(role: Any) -> bool:
    return normalize_user_role(role) in SUPERADMIN_ROLE_VALUES


def user_is_superadmin(user: Any) -> bool:
    return role_is_superadmin(getattr(user, "role", None))


def user_has_organization_scope(user: Any) -> bool:
    role = normalize_user_role(getattr(user, "role", None))
    return role in {DVTDefaultRoles.ADMIN.value, DVTDefaultRoles.USER.value}


def user_has_organization_wide_access(user: Any) -> bool:
    role = normalize_user_role(getattr(user, "role", None))
    return role in {DVTDefaultRoles.ADMIN.value, DVTDefaultRoles.SUPERADMIN.value}