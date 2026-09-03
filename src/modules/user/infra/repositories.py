import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from .db_models import UserRecord as UserModel

from ..domain.entities import User as UserEntity
from ..domain.repositories import UserRepository
from ..flow.exceptions import UserNotFoundError
from .mappers import (
    persisted_user_to_entity,
    update_persisted_user_from_entity,
    user_entity_to_persisted,
)


class SQLAlchemyUserRepository(UserRepository):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, user_id: str) -> UserEntity | None:
        persisted_user = await self.session.get(UserModel, user_id)
        if persisted_user is None:
            return None
        return persisted_user_to_entity(persisted_user)

    async def get_by_organization_id(self, organization_id: str) -> list[UserEntity]:
        stmt = sa.select(UserModel).where(UserModel.organization_id == organization_id)

        models = (await self.session.scalars(stmt)).all()

        return [persisted_user_to_entity(model) for model in models]

    async def get_by_role(self, role: str) -> list[UserEntity]:
        stmt = sa.select(UserModel).where(UserModel.role == role)

        models = (await self.session.scalars(stmt)).all()

        return [persisted_user_to_entity(model) for model in models]

    async def add(self, user: UserEntity) -> UserEntity:
        model = user_entity_to_persisted(user)
        self.session.add(model)
        await self.session.refresh(model)
        return persisted_user_to_entity(model)

    async def update(self, user: UserEntity) -> UserEntity:
        model = await self.session.get(UserModel, user.id)

        if model is None:
            raise UserNotFoundError(user.id)

        model = update_persisted_user_from_entity(model, user)
        return persisted_user_to_entity(model)

    async def delete(self, user_id: str) -> None:
        model = await self.session.get(UserModel, user_id)

        if model is None:
            raise UserNotFoundError(user_id)

        await self.session.delete(model)
