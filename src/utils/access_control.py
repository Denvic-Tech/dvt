from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa

from src.utils.user_roles import user_has_admin_access, user_has_global_access


@dataclass(frozen=True, slots=True)
class AccessScope:
    organization_id: str | None
    owner_user_id: str | None

    @property
    def is_owner_scoped(self) -> bool:
        return self.owner_user_id is not None


def build_owner_or_org_filters(
    *,
    user: Any,
    organization_column,
    owner_column,
) -> list[sa.ColumnElement[bool]]:
    if user_has_global_access(user):
        return []

    filters = [organization_column == getattr(user, "organization_id")]
    if user_has_admin_access(user):
        return filters

    filters.append(owner_column == getattr(user, "id"))
    return filters


def build_org_only_filters(
    *,
    user: Any,
    organization_column,
) -> list[sa.ColumnElement[bool]]:
    if user_has_global_access(user):
        return []

    return [organization_column == getattr(user, "organization_id")]


def can_manage_organization(actor: Any, organization_id: str | None) -> bool:
    if organization_id is None:
        return True
    if user_has_global_access(actor):
        return True
    return getattr(actor, "organization_id", None) == organization_id


def get_access_scope(user: Any) -> AccessScope:
    if user_has_global_access(user):
        return AccessScope(organization_id=None, owner_user_id=None)
    if user_has_admin_access(user):
        return AccessScope(
            organization_id=getattr(user, "organization_id"),
            owner_user_id=None,
        )
    return AccessScope(
        organization_id=getattr(user, "organization_id"),
        owner_user_id=getattr(user, "id"),
    )
