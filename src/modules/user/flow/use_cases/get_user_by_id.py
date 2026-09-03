from ...domain.entities import User
from ...domain.repositories import UserRepository
from ..exceptions import UserNotFoundError


class GetUserByIDUseCase:
    def __init__(self, repository: UserRepository) -> None:
        self.repository = repository

    async def execute(self, user_id: str) -> User:
        user = await self.repository.get(user_id)

        if user is None:
            raise UserNotFoundError(user_id)

        return user
