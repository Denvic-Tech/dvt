from ...domain.entities import MCPToken
from ...domain.repositories import MCPTokenRepository


class ListMCPToken:
    def __init__(self, repository: MCPTokenRepository) -> None:
        self._repository = repository

    async def execute(self, *, user_id: str) -> list[MCPToken]:
        return await self._repository.list_for_user(user_id)
