from typing import Annotated

from fastapi import Depends
from usrak.core import exceptions as exc
from usrak.core.dependencies.user import (
    get_user_access_only as usrak_get_user_access_only,
    get_user_api_only as usrak_get_user_api_only,
    get_user_verified_and_active as usrak_get_user_verified_and_active,
)

from src.modules.user.infra.db_models import UserRecord
from src.utils.user_roles import user_has_admin_access, user_is_superadmin

UsrakUserAccessOnly = Annotated[UserRecord, Depends(usrak_get_user_access_only)]
UsrakUserApiOnly = Annotated[UserRecord, Depends(usrak_get_user_api_only)]


async def get_user_access_only(
    user: UsrakUserAccessOnly,
):
    if not user.is_verified:
        raise exc.UserNotVerifiedException()
    if not user.is_active:
        raise exc.UserDeactivatedException()

    return user


async def get_user_api_only(
    user: UsrakUserApiOnly,
):
    if not user.is_verified:
        raise exc.UserNotVerifiedException()
    if not user.is_active:
        raise exc.UserDeactivatedException()

    return user


async def get_user_any_auth(
        user: Annotated[UserRecord, Depends(usrak_get_user_verified_and_active)]
):
    return user


async def get_user_admin_access_only(
    user: UsrakUserAccessOnly,
):
    if not user.is_verified:
        raise exc.UserNotVerifiedException()
    if not user.is_active:
        raise exc.UserDeactivatedException()
    if not user_has_admin_access(user):
        raise exc.AccessDeniedException()

    return user


async def get_user_superadmin_access_only(
    user: UsrakUserAccessOnly,
):
    if not user.is_verified:
        raise exc.UserNotVerifiedException()
    if not user.is_active:
        raise exc.UserDeactivatedException()
    if not user_is_superadmin(user):
        raise exc.AccessDeniedException()

    return user


async def get_user_superadmin_api_only(
    user: UsrakUserApiOnly,
):
    if not user.is_verified:
        raise exc.UserNotVerifiedException()
    if not user.is_active:
        raise exc.UserDeactivatedException()
    if not user_is_superadmin(user):
        raise exc.AccessDeniedException()

    return user


UserAccessOnly = Annotated[UserRecord, Depends(get_user_access_only)]
UserApiOnly = Annotated[UserRecord, Depends(get_user_api_only)]
UserAnyAuth = Annotated[UserRecord, Depends(get_user_any_auth)]
UserAdminAccessOnly = Annotated[UserRecord, Depends(get_user_admin_access_only)]
UserSuperadminAccessOnly = Annotated[UserRecord, Depends(get_user_superadmin_access_only)]
UserSuperadminApiOnly = Annotated[UserRecord, Depends(get_user_superadmin_access_only)]
