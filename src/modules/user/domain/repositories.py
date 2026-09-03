from typing import Protocol

from .entities.user import User


class UserRepository(Protocol):
    async def get(self, user_id: str) -> User | None:
        ...

    async def get_by_organization_id(self, organization_id: str) -> list[User]:
        ...

    async def get_by_role(self, role: str) -> list[User]:
        ...

    async def add(self, user: User) -> User:
        ...

    async def update(self, user: User) -> User:
        ...

    async def delete(self, user_id: str) -> None:
        ...
