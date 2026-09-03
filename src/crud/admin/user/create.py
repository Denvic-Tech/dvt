from sqlalchemy.ext.asyncio import AsyncSession
from usrak.core.security import hash_password

from src.crud.admin import user as admin_user_crud
from src.enums import DVTDefaultRoles
from src.modules.user.infra.db_models import UserRecord
from src.utils import user_roles as user_roles_utils


async def create_user(
        session: AsyncSession,
        *,
        email: str,
        username: str,
        password: str,
        organization_id: str,
        role: str = DVTDefaultRoles.USER.value,
) -> UserRecord:
    existing_user = (await admin_user_crud.get_users_by(session, email=email)).first()
    if existing_user is not None:
        raise admin_user_crud.UserAlreadyExistsException()

    user = UserRecord(
        email=email,
        user_name=username,
        hashed_password=hash_password(password),
        auth_provider="email",
        is_verified=True,
        is_active=True,
        role=user_roles_utils.normalize_user_role(role) or DVTDefaultRoles.USER.value,
        organization_id=organization_id,
    )
    session.add(user)
    await session.flush([user])
    return user
