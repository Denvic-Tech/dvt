from dataclasses import replace

from db_connection import AccessDeniedError, ConnectionDraft, ConnectionPatch
from db_connection.application import AccessContext, AccessPolicy
from db_connection.domain import ConnectionListQuery, ConnectionRecord

from src.utils.user_roles import user_has_admin_access, user_has_global_access

from ..domain.helpers import (
    extract_connection_draft_or_patch_owner,
    extract_connection_record_owner,
)
from .actor import DVTActor


class DVTAccessPolicy(AccessPolicy):
    async def scope_list(self, ctx: AccessContext, query: ConnectionListQuery) -> ConnectionListQuery:
        actor = self._require_actor(ctx)

        if user_has_global_access(actor):
            return query

        extra_filters = dict(query.extra_filters)
        extra_filters["organization_id"] = getattr(actor, "organization_id", None)

        if not user_has_admin_access(actor):
            extra_filters["user_id"] = getattr(actor, "id", None)

        return replace(query, extra_filters=extra_filters)

    async def can_create(self, ctx: AccessContext, draft: ConnectionDraft) -> None:
        actor = self._require_actor(ctx)

        if user_has_global_access(actor):
            return

        draft_owner = extract_connection_draft_or_patch_owner(draft)

        if user_has_admin_access(actor):
            if draft_owner.organization_id is not None and actor.organization_id != draft_owner.organization_id:
                raise AccessDeniedError(
                    "Cannot create connection for another organization.",
                    details={"organization_id": draft_owner.organization_id},
                )
            return

        if draft_owner.organization_id is not None and actor.organization_id != draft_owner.organization_id:
            raise AccessDeniedError(
                "Cannot create connection for another organization.",
                details={"organization_id": draft_owner.organization_id},
            )

        if draft_owner.id is not None and actor.id != draft_owner.id:
            raise AccessDeniedError(
                "Cannot create connection for another user.",
                details={"user_id": draft_owner.id},
            )

    async def can_get_one(self, ctx: AccessContext, existing: ConnectionRecord) -> None:
        actor = self._require_actor(ctx)

        if user_has_global_access(actor):
            return

        existing_owner = extract_connection_record_owner(existing)

        if user_has_admin_access(actor):
            if actor.organization_id != existing_owner.organization_id:
                raise AccessDeniedError(
                    "Cannot get another organization's connection.",
                    details={"organization_id": existing_owner.organization_id},
                )
            return

        if actor.id != existing_owner.id or actor.organization_id != existing_owner.organization_id:
            raise AccessDeniedError(
                "Cannot get another user's connection.",
                details={
                    "user_id": existing_owner.id,
                    "organization_id": existing_owner.organization_id,
                },
            )

    async def can_update(self, ctx: AccessContext, existing: ConnectionRecord, patch: ConnectionPatch) -> None:
        actor = self._require_actor(ctx)

        if user_has_global_access(actor):
            return

        existing_owner = extract_connection_record_owner(existing)
        patch_owner = extract_connection_draft_or_patch_owner(patch)

        if user_has_admin_access(actor):
            if actor.organization_id != existing_owner.organization_id:
                raise AccessDeniedError(
                    "Cannot update another organization's connection.",
                    details={"organization_id": existing_owner.organization_id},
                )

            if patch_owner.organization_id is not None and actor.organization_id != patch_owner.organization_id:
                raise AccessDeniedError(
                    "Cannot update connection to another organization.",
                    details={"organization_id": patch_owner.organization_id},
                )
            return

        if actor.id != existing_owner.id or actor.organization_id != existing_owner.organization_id:
            raise AccessDeniedError(
                "Cannot update another user's connection.",
                details={
                    "user_id": existing_owner.id,
                    "organization_id": existing_owner.organization_id,
                },
            )

        if patch_owner.organization_id is not None and actor.organization_id != patch_owner.organization_id:
            raise AccessDeniedError(
                "Cannot update connection to another organization.",
                details={"organization_id": patch_owner.organization_id},
            )

        if patch_owner.id is not None and actor.id != patch_owner.id:
            raise AccessDeniedError(
                "Cannot update connection to another user.",
                details={"user_id": patch_owner.id},
            )

    async def can_delete(self, ctx: AccessContext, existing: ConnectionRecord) -> None:
        actor = self._require_actor(ctx)

        if user_has_global_access(actor):
            return

        existing_owner = extract_connection_record_owner(existing)

        if user_has_admin_access(actor):
            if actor.organization_id != existing_owner.organization_id:
                raise AccessDeniedError(
                    "Cannot delete another organization's connection.",
                    details={"organization_id": existing_owner.organization_id},
                )
            return

        if actor.id != existing_owner.id or actor.organization_id != existing_owner.organization_id:
            raise AccessDeniedError(
                "Cannot delete another user's connection.",
                details={
                    "user_id": existing_owner.id,
                    "organization_id": existing_owner.organization_id,
                },
            )

    @staticmethod
    def _require_actor(ctx: AccessContext) -> DVTActor:
        actor = ctx.actor
        if actor is None:
            raise AccessDeniedError(
                "Authenticated actor is required.",
                details={"operation": ctx.operation},
            )
        return actor
