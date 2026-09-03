from fastapi import APIRouter
from sqlalchemy.ext.asyncio import AsyncSession

from services.gateway.exceptions.admin import user as admin_user_exc
from services.gateway.policies import admin_user as admin_user_policy

from src.crud.admin import user as admin_user_crud
from src.modules.user.infra.db_models import UserRecord
from src.schemas.http.admin.user import (
    AdminUserCreateSchema,
    AdminUserReadSchema,
    AdminUserUpdateSchema,
)
from src.schemas.http.common import CommonResponse
from src.utils.access_control import can_manage_organization
from src.utils.user_roles import user_has_global_access

router = r = APIRouter()


async def get_user_by_id_route_impl(
        session: AsyncSession,
        user: UserRecord,
        user_id: str,
):
    admin_user_policy.ensure_admin_access(user)
    target_user = (await admin_user_crud.get_users_by(
        session,
        user_id=user_id,
    )).first()
    if not target_user:
        raise admin_user_exc.UserNotFoundHTTPError()
    if not can_manage_organization(user, target_user.organization_id):
        raise admin_user_exc.UserNotFoundHTTPError()

    return AdminUserReadSchema.model_validate(target_user, from_attributes=True)


async def get_users_route_impl(
        session: AsyncSession,
        user: UserRecord,
        page: int = 1,
        limit: int = 30,
        email_contains: str | None = None,
):
    admin_user_policy.ensure_admin_access(user)
    page = max(page, 1)
    limit = max(limit, 1)

    offset = (page - 1) * limit

    users = (await admin_user_crud.get_users_by(
        session,
        limit=limit,
        offset=offset,
        email_contains=email_contains,
        organization_id=None if user_has_global_access(user) else user.organization_id,
    )).all()

    return [AdminUserReadSchema.model_validate(u, from_attributes=True) for u in users]


async def update_user_route_impl(
        user_data: AdminUserUpdateSchema,
        session: AsyncSession,
        user: UserRecord
):
    admin_user_policy.ensure_admin_access(user)
    admin_user_policy.ensure_self_update_allowed(user, user_data)

    target_user = (await admin_user_crud.get_users_by(
        session,
        user_id=user_data.user_id,
    )).first()
    if not target_user:
        raise admin_user_exc.UserNotFoundHTTPError()
    if not user_has_global_access(user) and target_user.organization_id != user.organization_id:
        raise admin_user_exc.UserNotFoundHTTPError()

    _current_user_edit = user.id == user_data.user_id
    target_organization_id = (
        user_data.organization_id
        if user_has_global_access(user) and user_data.organization_id is not None
        else target_user.organization_id if _current_user_edit else user.organization_id
    )
    updated_user = await admin_user_crud.update_user(
        session=session,
        user_id=user_data.user_id,
        email=user_data.email,
        username=user_data.user_name,
        password=user_data.password,
        role=user_data.role if not _current_user_edit else None,
        is_active=user_data.is_active if not _current_user_edit else None,
        is_verified=user_data.is_verified if not _current_user_edit else None,
        organization_id=target_organization_id,
    )
    if updated_user is None:
        raise admin_user_exc.UserNotFoundHTTPError()
    await session.commit()
    await session.refresh(updated_user)

    return CommonResponse(
        success=True,
        message=f"User successfully updated"
    )


async def create_user_route_impl(
        session: AsyncSession,
        user: UserRecord,
        user_data: AdminUserCreateSchema,
):
    admin_user_policy.ensure_admin_access(user)
    organization_id = user_data.organization_id or user.organization_id
    if not can_manage_organization(user, organization_id):
        organization_id = user.organization_id
    try:
        await admin_user_crud.create_user(
            session,
            email=user_data.email,
            username=user_data.user_name,
            password=user_data.password,
            organization_id=organization_id,
            role=user_data.role,
        )
    except admin_user_crud.UserAlreadyExistsException as exc:
        raise admin_user_exc.UserAlreadyExistsHTTPError from exc
    await session.commit()

    return CommonResponse(
        success=True,
        message=f"User successfully created"
    )


async def delete_user_route_impl(
        user_id: str,
        session: AsyncSession,
        user: UserRecord,
):
    admin_user_policy.ensure_admin_access(user)
    target_user = (await admin_user_crud.get_users_by(
        session,
        user_id=user_id,
    )).first()
    if not target_user:
        raise admin_user_exc.UserNotFoundHTTPError()
    if not user_has_global_access(user) and target_user.organization_id != user.organization_id:
        raise admin_user_exc.UserNotFoundHTTPError()

    admin_user_policy.ensure_self_delete_allowed(user, target_user)

    await admin_user_crud.delete_users(session, [target_user])
    await session.commit()

    return CommonResponse(
        success=True,
        message=f"User successfully deleted"
    )
