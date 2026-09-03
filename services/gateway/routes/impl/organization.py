from sqlalchemy.ext.asyncio import AsyncSession

from services.gateway.exceptions import organization as org_exc
from services.gateway.policies import organization as org_policy

from src.crud import organization as org_crud
from src.modules.user.infra.db_models import UserRecord
from src.schemas.http.common import CommonResponse
from src.schemas.http.organization import (
    OrganizationCreateSchema,
    OrganizationReadSchema,
    OrganizationUpdateSchema,
)
from src.utils import access_control, user_roles


def _organization_to_read_schema(
    organization,
    *,
    projects_count: int,
) -> OrganizationReadSchema:
    return OrganizationReadSchema.model_validate(
        {
            **organization.model_dump(),
            "projects_count": projects_count,
        }
    )


async def get_organizations_route_impl(
    session: AsyncSession,
    user: UserRecord,
) -> list[OrganizationReadSchema]:
    organizations = (
        (await org_crud.get_organizations(session)).all()
        if access_control.user_has_global_access(user)
        else (await org_crud.get_organizations_by(session, organization_id=user.organization_id)).all()
    )
    projects_counts = await org_crud.get_projects_count_by_organization_ids(
        session,
        organization_ids=[organization.id for organization in organizations],
    )
    return [
        _organization_to_read_schema(
            organization,
            projects_count=projects_counts.get(organization.id, 0),
        )
        for organization in organizations
    ]


async def get_organization_route_impl(
    organization_id: str,
    session: AsyncSession,
    user: UserRecord,
) -> OrganizationReadSchema:
    organization = (await org_crud.get_organizations_by(session, organization_id=organization_id)).first()
    if organization is None or not access_control.can_manage_organization(user, organization.id):
        raise org_exc.OrganizationNotFoundHTTPError

    projects_count = (
        await org_crud.get_projects_count_by_organization_ids(
            session,
            organization_ids=[organization.id],
        )
    ).get(organization.id, 0)
    return _organization_to_read_schema(organization, projects_count=projects_count)


async def create_organization_route_impl(
    data: OrganizationCreateSchema,
    session: AsyncSession,
    user: UserRecord,
) -> OrganizationReadSchema:
    if not user_roles.user_has_global_access(user):
        raise org_exc.OrganizationForbiddenHttpError

    try:
        normalized_inn = org_policy.normalize_organization_inn(data.inn)
        organization = await org_crud.create_organization(
            session,
            name=data.name,
            description=data.description,
            inn=normalized_inn,
            is_active=data.is_active,
        )
    except org_crud.OrganizationINNConflictError:
        raise org_exc.OrganizationINNConflictHTTPError

    await session.commit()
    await session.refresh(organization)
    return OrganizationReadSchema.model_validate(organization)


async def update_organization_route_impl(
    organization_id: str,
    data: OrganizationUpdateSchema,
    session: AsyncSession,
    user: UserRecord,
) -> OrganizationReadSchema:
    if not user_roles.user_has_admin_access(user):
        raise org_exc.OrganizationForbiddenHttpError

    organization = (await org_crud.get_organizations_by(session, organization_id=organization_id)).first()
    if organization is None or not access_control.can_manage_organization(user, organization.id):
        raise org_exc.OrganizationNotFoundHTTPError

    update_data = data.model_dump(exclude_unset=True)
    if "inn" in update_data:
        update_data["inn"] = org_policy.normalize_organization_inn(update_data["inn"])

    try:
        updated_organization = await org_crud.update_organization(
            session,
            organization_id=organization_id,
            **update_data,
        )
    except org_crud.OrganizationINNConflictError as exc:
        raise org_exc.OrganizationINNConflictHTTPError

    if updated_organization is None:
        raise org_exc.OrganizationNotFoundHTTPError

    await session.commit()
    await session.refresh(updated_organization)
    return OrganizationReadSchema.model_validate(updated_organization)


async def delete_organization_route_impl(
    organization_id: str,
    session: AsyncSession,
    user: UserRecord,
) -> CommonResponse:
    if not access_control.user_has_global_access(user):
        raise org_exc.OrganizationForbiddenHttpError

    organization = (await org_crud.get_organizations_by(session, organization_id=organization_id)).first()
    if organization is None:
        raise org_exc.OrganizationNotFoundHTTPError

    if user.organization_id == organization_id:
        raise org_exc.OrganizationForbiddenHttpError

    dependency_counts = await org_crud.get_organization_dependency_counts(
        session,
        organization_id=organization_id,
    )
    if any(dependency_counts.values()):
        raise org_exc.OrganizationINNConflictHTTPError

    await org_crud.delete_organization(session, organization)
    await session.commit()
    return CommonResponse(success=True, message="Organization successfully deleted.")
