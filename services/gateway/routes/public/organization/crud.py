from typing import Annotated

from fastapi import APIRouter, Depends
from usrak.core.dependencies.user import build_user_dependency
from usrak.core.enums import AuthMode

from services.gateway.routes.impl import organization as org_impl

from src.db.fastapi.dependencies import AsyncSessionDepends
from src.modules.user.infra.db_models import UserRecord
from src.schemas.http.common import CommonResponse
from src.schemas.http.organization import (
    OrganizationCreateSchema,
    OrganizationReadSchema,
    OrganizationUpdateSchema,
)

r = router = APIRouter()


_get_user = build_user_dependency(
    auth_mode=AuthMode.API_ONLY,
    require_active=True,
    require_verified=True
)
UserDepends = Annotated[UserRecord, Depends(_get_user)]


@router.get("", response_model=list[OrganizationReadSchema])
async def get_organizations(
        session: AsyncSessionDepends,
        user: UserDepends,
) -> list[OrganizationReadSchema]:
    return await org_impl.get_organizations_route_impl(
        session=session,
        user=user
    )


@router.get("/{organization_id}", response_model=OrganizationReadSchema)
async def get_organization(
        organization_id: str,
        session: AsyncSessionDepends,
        user: UserDepends,
) -> OrganizationReadSchema:
    return await org_impl.get_organization_route_impl(
        organization_id=organization_id,
        session=session,
        user=user
    )


@router.post("", response_model=OrganizationReadSchema)
async def create_organization(
        data: OrganizationCreateSchema,
        session: AsyncSessionDepends,
        user: UserDepends,
) -> OrganizationReadSchema:
    return await org_impl.create_organization_route_impl(
        data=data,
        session=session,
        user=user
    )


@router.patch("/{organization_id}", response_model=OrganizationReadSchema)
async def update_organization(
        organization_id: str,
        data: OrganizationUpdateSchema,
        session: AsyncSessionDepends,
        user: UserDepends,
) -> OrganizationReadSchema:
    return await org_impl.update_organization_route_impl(
        organization_id=organization_id,
        data=data,
        session=session,
        user=user
    )


@router.delete("/{organization_id}", response_model=CommonResponse)
async def delete_organization(
        organization_id: str,
        session: AsyncSessionDepends,
        user: UserDepends,
) -> CommonResponse:
    return await org_impl.delete_organization_route_impl(
        organization_id=organization_id,
        session=session,
        user=user
    )
