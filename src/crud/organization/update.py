from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from src.crud.organization._session import maybe_await
from src.crud.organization.exceptions import OrganizationINNConflictException
from src.crud.organization.read import get_organizations_by
from src.models import OrganizationRecord

_UNSET = object()


async def update_organization(
    session: AsyncSession,
    *,
    organization_id: str,
    name: str | None | object = _UNSET,
    description: str | None | object = _UNSET,
    inn: str | None | object = _UNSET,
    is_active: bool | object = _UNSET,
) -> OrganizationRecord | None:
    organization = (await get_organizations_by(session, organization_id=organization_id)).first()
    if organization is None:
        return None

    if inn is not _UNSET:
        normalized_inn = inn or None
        if normalized_inn != organization.inn and normalized_inn is not None:
            existing_organization = (await get_organizations_by(session, inn=normalized_inn)).first()
            if existing_organization is not None and existing_organization.id != organization_id:
                raise OrganizationINNConflictException()
        organization.inn = normalized_inn

    if name is not _UNSET:
        organization.name = name

    if description is not _UNSET:
        organization.description = description

    if is_active is not _UNSET:
        organization.is_active = is_active

    organization.updated_at = datetime.now(tz=UTC)
    session.add(organization)
    await maybe_await(session.flush([organization]))
    return organization
