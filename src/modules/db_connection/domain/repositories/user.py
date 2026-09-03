from typing import Protocol

from ..entities.user import ExistingUser


class UserRepository(Protocol):
    async def get(self, user_id: str) -> ExistingUser | None:
        ...
