import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src.enums import DVTDefaultRoles
from src.modules.user.infra.db_models import UserRecord

from .exceptions import UserNotFoundException


async def get_users(
        session: AsyncSession,
        *filters: sa.ColumnExpressionArgument[bool],
        limit: int | None = None,
        offset: int | None = None,
) -> sa.ScalarResult[UserRecord]:
    stmt = sa.select(UserRecord).where(*filters)

    if offset is not None:
        stmt = stmt.offset(offset)

    if limit is not None:
        stmt = stmt.limit(limit)

    return (await session.execute(stmt)).scalars()


async def get_users_by(
        session: AsyncSession,
        *,
        user_id: str | None = None,
        email: str | None = None,
        user_name: str | None = None,
        role: str | None = None,
        is_active: bool | None = None,
        is_verified: bool | None = None,
        organization_id: str | None = None,
        email_contains: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
) -> sa.ScalarResult[UserRecord]:
    filters: list[sa.ColumnExpressionArgument[bool]] = []

    if user_id is not None:
        filters.append(UserRecord.id == user_id)

    if email is not None:
        filters.append(UserRecord.email == email)

    if user_name is not None:
        filters.append(UserRecord.user_name == user_name)

    if role is not None:
        filters.append(UserRecord.role == role)

    if is_active is not None:
        filters.append(UserRecord.is_active.is_(is_active))

    if is_verified is not None:
        filters.append(UserRecord.is_verified.is_(is_verified))

    if organization_id is not None:
        filters.append(UserRecord.organization_id == organization_id)

    if email_contains:
        filters.append(UserRecord.email.ilike(f"%{email_contains}%"))

    return await get_users(
        session,
        *filters,
        limit=limit,
        offset=offset,
    )


async def get_default_service_user(
        session: AsyncSession,
) -> UserRecord:
    stmt = (
        sa.select(UserRecord)
        .where(
            UserRecord.role.in_(
                [
                    DVTDefaultRoles.SUPERADMIN.value,
                    DVTDefaultRoles.ADMIN.value,
                ]
            ),
            UserRecord.is_active.is_(True),
            UserRecord.is_verified.is_(True),
        )
        .order_by(
            sa.case(
                (UserRecord.role == DVTDefaultRoles.SUPERADMIN.value, 0),
                else_=1,
            ),
            UserRecord.signed_up_at.asc(),
            UserRecord.id.asc(),
        )
    )
    user = (await session.execute(stmt)).scalars().first()
    if not user:
        raise UserNotFoundException()

    return user
