from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from usrak.core.security import hash_password

from src.crud.admin.user.read import get_users_by
from src.modules.user.infra.db_models import UserRecord
from src.utils.user_roles import normalize_user_role


async def update_user(
        session: AsyncSession,
        *,
        user_id: str,
        email: str | None = None,
        username: str | None = None,
        password: str | None = None,
        role: str | None = None,
        is_active: bool | None = None,
        is_verified: bool | None = None,
        organization_id: str | None = None,
) -> UserRecord | None:
    user = (await get_users_by(session, user_id=user_id)).first()
    if user is None:
        return None

    update_values: dict[str, object] = {}

    if email is not None:
        update_values["email"] = email

    if username is not None:
        update_values["user_name"] = username

    if role is not None:
        normalized_role = normalize_user_role(role)
        if normalized_role is not None:
            update_values["role"] = normalized_role

    if is_active is not None:
        update_values["is_active"] = is_active

    if is_verified is not None:
        update_values["is_verified"] = is_verified

    if organization_id is not None:
        update_values["organization_id"] = organization_id

    if password:
        update_values["hashed_password"] = hash_password(password)
        update_values["password_version"] = user.password_version + 1
        update_values["last_password_change"] = datetime.now(UTC)

    if not update_values:
        return user

    stmt = (
        sa.update(UserRecord)
        .where(UserRecord.id == user_id)
        .values(**update_values)
        .execution_options(synchronize_session="fetch")
    )
    await session.execute(stmt)
    await session.flush()
    await session.refresh(user)
    return user
