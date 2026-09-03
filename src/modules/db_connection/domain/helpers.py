from db_connection.domain.entities import ConnectionDraft, ConnectionPatch, ConnectionRecord
from db_connection.errors import AccessDeniedError

from .entities import DraftOrPatchUser, ExistingUser


def extract_connection_draft_or_patch_owner(
    draft_or_patch: ConnectionDraft | ConnectionPatch,
) -> DraftOrPatchUser:
    user_id = draft_or_patch.extra.get("user_id")
    organization_id = draft_or_patch.extra.get("organization_id")

    return DraftOrPatchUser(
        id=user_id,
        organization_id=organization_id,
    )


def extract_connection_record_owner(record: ConnectionRecord) -> ExistingUser:
    user_id = record.extra.get("user_id")
    organization_id = record.extra.get("organization_id")

    if not isinstance(user_id, str) or not user_id:
        raise AccessDeniedError("Connection user_id is required.")

    if not isinstance(organization_id, str) or not organization_id:
        raise AccessDeniedError("Connection organization_id is required.")

    return ExistingUser(
        id=user_id,
        organization_id=organization_id,
    )