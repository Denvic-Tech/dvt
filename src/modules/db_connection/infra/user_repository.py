from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.user.domain.repositories import UserRepository as DVTUserRepository

from ..domain.entities import ExistingUser
from ..domain.repositories import UserRepository


class ExternalUserRepositoryFactory(Protocol):
    def __call__(self, session: AsyncSession) -> DVTUserRepository:
        ...


class SessionScopedUserRepository(UserRepository):
    def __init__(
        self,
        session_factory: Callable[[], AbstractAsyncContextManager[AsyncSession]],
        user_repository_factory: ExternalUserRepositoryFactory,
    ) -> None:
        self._session_factory = session_factory
        self._user_repository_factory = user_repository_factory

    async def get(self, user_id: str) -> ExistingUser | None:
        async with self._session_factory() as session:
            user_repository = self._user_repository_factory(session)
            user = await user_repository.get(user_id)

        if user is None:
            return None

        return ExistingUser(
            id=user.id,
            organization_id=user.organization_id,
        )
