from typing import Annotated

from fastapi import APIRouter, Depends
from usrak.core.dependencies.user import build_user_dependency
from usrak.core.enums import AuthMode

from services.gateway.routes.impl.admin import user as admin_user_impl

from src.db.fastapi.dependencies import AsyncSessionDepends
from src.enums import DVTDefaultRoles
from src.modules.user.infra.db_models import UserRecord
from src.schemas.http.admin.user import (
    AdminUserCreateSchema,
    AdminUserReadSchema,
    AdminUserUpdateSchema,
)
from src.schemas.http.common import CommonResponse

router = r = APIRouter()


_get_user = build_user_dependency(
    auth_mode=AuthMode.ACCESS_ONLY,
    require_active=True,
    require_verified=True,
    require_roles=[DVTDefaultRoles.SUPERADMIN, DVTDefaultRoles.ADMIN],
)
UserDepends = Annotated[UserRecord, Depends(_get_user)]


@r.get('/{user_id}', response_model=AdminUserReadSchema)
async def get_user_by_id(
        user_id: str,
        session: AsyncSessionDepends,
        user: UserDepends,
):
    return await admin_user_impl.get_user_by_id_route_impl(
        session=session,
        user=user,
        user_id=user_id,
    )


@r.get('', response_model=list[AdminUserReadSchema])
async def get_users(
        session: AsyncSessionDepends,
        user: UserDepends,
        page: int = 1,
        limit: int = 30,
        email_contains: str | None = None,
):
    return await admin_user_impl.get_users_route_impl(
        session=session,
        user=user,
        page=page,
        limit=limit,
        email_contains=email_contains,
    )


@r.patch('', response_model=CommonResponse)
async def update_user(
        user_data: AdminUserUpdateSchema,
        session: AsyncSessionDepends,
        user: UserDepends
):
    return await admin_user_impl.update_user_route_impl(
        session=session,
        user=user,
        user_data=user_data,
    )


@r.post('', response_model=CommonResponse)
async def create_user(
        user_data: AdminUserCreateSchema,
        session: AsyncSessionDepends,
        user: UserDepends,
):
    return await admin_user_impl.create_user_route_impl(
        session=session,
        user=user,
        user_data=user_data,
    )


@r.delete('/{user_id}', response_model=CommonResponse)
async def delete_user(
        user_id: str,
        session: AsyncSessionDepends,
        user: UserDepends,
):
    return await admin_user_impl.delete_user_route_impl(
        session=session,
        user=user,
        user_id=user_id,
    )
