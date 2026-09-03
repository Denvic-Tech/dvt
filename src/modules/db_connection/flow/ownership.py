from __future__ import annotations

from dataclasses import replace

from db_connection import (
    AccessDeniedError,
    ConnectionDraft,
    ConnectionOwnershipResolver,
    ConnectionPatch,
    ValidationFailedError,
)
from db_connection.domain import patch_fields_set, patch_to_dict
from src.utils.user_roles import user_has_admin_access, user_has_global_access

from ..domain.entities import ConnectionRecord, DraftOrPatchUser, ExistingUser
from ..domain.helpers import (
    extract_connection_draft_or_patch_owner,
    extract_connection_record_owner,
)
from ..domain.repositories import UserRepository
from .actor import DVTActor


class DVTConnectionOwnershipResolver(ConnectionOwnershipResolver):
    def __init__(
        self,
        user_repository: UserRepository,
    ) -> None:
        self._user_repository = user_repository

    async def resolve_create(self, ctx, draft: ConnectionDraft) -> ConnectionDraft:
        actor = self._require_actor(ctx)
        owner = await self._resolve_owner_for_create(
            actor=actor,
            requested=extract_connection_draft_or_patch_owner(draft),
        )
        return replace(
            draft,
            extra=self._with_owner(extra=draft.extra, owner=owner),
        )

    async def resolve_patch(
        self,
        ctx,
        existing: ConnectionRecord,
        patch: ConnectionPatch,
    ) -> ConnectionPatch:
        if "extra" not in patch_fields_set(patch):
            return patch

        requested_extra = dict(patch.extra or {})
        patch_extra = dict(existing.extra)
        patch_extra.update(requested_extra)
        existing_owner = extract_connection_record_owner(existing)
        owner_override_requested = (
            "user_id" in requested_extra or "organization_id" in requested_extra
        )

        if owner_override_requested:
            actor = self._require_actor(ctx)
            owner = await self._resolve_owner_for_patch(
                actor=actor,
                existing=existing_owner,
                requested=DraftOrPatchUser(
                    id=requested_extra.get("user_id"),
                    organization_id=requested_extra.get("organization_id"),
                ),
            )
        else:
            owner = existing_owner

        patch_extra["user_id"] = owner.id
        patch_extra["organization_id"] = owner.organization_id
        patch_data = patch_to_dict(patch)
        patch_data["extra"] = patch_extra
        return ConnectionPatch(**patch_data)

    async def _resolve_owner_for_create(
        self,
        *,
        actor: DVTActor,
        requested: DraftOrPatchUser,
    ) -> ExistingUser:
        if user_has_global_access(actor):
            return await self._validate_owner(
                user_id=requested.id or actor.id,
                organization_id=requested.organization_id or actor.organization_id,
            )

        if user_has_admin_access(actor):
            self._assert_same_organization(
                actor=actor,
                organization_id=requested.organization_id,
                message="Cannot create connection for another organization.",
            )
            return await self._validate_owner(
                user_id=requested.id or actor.id,
                organization_id=actor.organization_id,
            )

        self._assert_same_organization(
            actor=actor,
            organization_id=requested.organization_id,
            message="Cannot create connection for another organization.",
        )
        self._assert_same_user(
            actor=actor,
            user_id=requested.id,
            message="Cannot create connection for another user.",
        )
        return await self._validate_owner(
            user_id=actor.id,
            organization_id=actor.organization_id,
        )

    async def _resolve_owner_for_patch(
        self,
        *,
        actor: DVTActor,
        existing: ExistingUser,
        requested: DraftOrPatchUser,
    ) -> ExistingUser:
        if user_has_global_access(actor):
            return await self._validate_owner(
                user_id=requested.id or existing.id,
                organization_id=requested.organization_id or existing.organization_id,
            )

        if user_has_admin_access(actor):
            self._assert_same_organization(
                actor=actor,
                organization_id=requested.organization_id,
                message="Cannot update connection to another organization.",
            )
            return await self._validate_owner(
                user_id=requested.id or existing.id,
                organization_id=actor.organization_id,
            )

        self._assert_same_organization(
            actor=actor,
            organization_id=requested.organization_id,
            message="Cannot update connection to another organization.",
        )
        self._assert_same_user(
            actor=actor,
            user_id=requested.id,
            message="Cannot update connection to another user.",
        )
        return await self._validate_owner(
            user_id=existing.id,
            organization_id=existing.organization_id,
        )

    async def _validate_owner(self, *, user_id: str, organization_id: str) -> ExistingUser:
        if not user_id:
            raise ValidationFailedError("Connection user_id is required.")
        if not organization_id:
            raise ValidationFailedError("Connection organization_id is required.")

        user = await self._user_repository.get(user_id)

        if user is None:
            raise ValidationFailedError(
                "Target user does not belong to the target organization.",
                details={
                    "user_id": user_id,
                    "organization_id": organization_id,
                },
            )

        if user.organization_id != organization_id:
            raise ValidationFailedError(
                "Target user does not belong to the target organization.",
                details={
                    "user_id": user_id,
                    "organization_id": organization_id,
                },
            )

        return ExistingUser(
            id=user_id,
            organization_id=organization_id,
        )

    @staticmethod
    def _with_owner(*, extra: dict[str, object], owner: ExistingUser) -> dict[str, object]:
        updated = dict(extra)
        updated["user_id"] = owner.id
        updated["organization_id"] = owner.organization_id
        return updated

    @staticmethod
    def _assert_same_organization(
        *,
        actor: DVTActor,
        organization_id: str | None,
        message: str,
    ) -> None:
        if organization_id is not None and organization_id != actor.organization_id:
            raise AccessDeniedError(
                message,
                details={"organization_id": organization_id},
            )

    @staticmethod
    def _assert_same_user(
        *,
        actor: DVTActor,
        user_id: str | None,
        message: str,
    ) -> None:
        if user_id is not None and user_id != actor.id:
            raise AccessDeniedError(
                message,
                details={"user_id": user_id},
            )

    @staticmethod
    def _require_actor(ctx) -> DVTActor:
        actor = ctx.actor
        if actor is None:
            raise AccessDeniedError(
                "Authenticated actor is required.",
                details={"operation": ctx.operation},
            )
        return actor
