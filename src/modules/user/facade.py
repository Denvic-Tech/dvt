from sqlalchemy.ext.asyncio import AsyncSession

from .flow.use_cases import GetUserByIDUseCase
from .infra.repositories import SQLAlchemyUserRepository


def build_get_user_by_id_use_case(
    session: AsyncSession,
) -> GetUserByIDUseCase:
    repo = SQLAlchemyUserRepository(session)
    return GetUserByIDUseCase(
        repository=repo
    )
