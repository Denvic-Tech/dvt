from sqlalchemy.ext.asyncio import AsyncSession

from src.crud.organization._session import maybe_await
from src.crud.organization.exceptions import OrganizationINNConflictException
from src.crud.organization.read import get_organizations_by
from src.models import OrganizationRecord


async def create_organization(
    session: AsyncSession,
    *,
    name: str,
    description: str | None = None,
    inn: str | None = None,
    is_active: bool = True,
) -> OrganizationRecord:
    normalized_inn = inn or None
    if normalized_inn is not None:
        existing_organization = (await get_organizations_by(session, inn=normalized_inn)).first()
        if existing_organization is not None:
            raise OrganizationINNConflictException()

    organization = OrganizationRecord(
        name=name,
        description=description,
        inn=normalized_inn,
        is_active=is_active,
    )
    session.add(organization)
    await maybe_await(session.flush([organization]))
    return organization
