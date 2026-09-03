from services.gateway.exceptions.admin import user as admin_user_exc

from src.modules.user.infra.db_models import UserRecord
from src.schemas.http.admin.user import AdminUserUpdateSchema
from src.utils.user_roles import normalize_user_role, user_has_admin_access


def ensure_admin_access(user: UserRecord) -> None:
    if not user_has_admin_access(user):
        raise admin_user_exc.UserActionForbiddenHTTPError("Admin access required")


def ensure_self_update_allowed(user: UserRecord, user_data: AdminUserUpdateSchema) -> None:
    if user.id != user_data.user_id:
        return

    requested_role = normalize_user_role(user_data.role)
    current_role = normalize_user_role(user.role)
    requested_organization_id = user_data.organization_id
    current_organization_id = user.organization_id

    if requested_role is not None and requested_role != current_role:
        raise admin_user_exc.UserActionForbiddenHTTPError("Cannot change own role")

    if (
        requested_organization_id is not None
        and requested_organization_id != current_organization_id
    ):
        raise admin_user_exc.UserActionForbiddenHTTPError("Cannot change own organization")


def ensure_self_delete_allowed(actor: UserRecord, target_user: UserRecord) -> None:
    if target_user.id == actor.id:
        raise admin_user_exc.UserActionForbiddenHTTPError("Cannot delete own account")
