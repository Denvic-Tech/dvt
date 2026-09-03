from dataclasses import replace

from ...domain.entities import MCPToken
from ...domain.exceptions import MCPTokenNotFoundError
from ...domain.repositories import MCPTokenRepository


class RevokeMCPToken:
    def __init__(self, repository: MCPTokenRepository) -> None:
        self._repository = repository

    async def execute(self, *, token_id: str, user_id: str) -> MCPToken:
        token = await self._repository.get_for_user(token_id, user_id)
        if token is None:
            raise MCPTokenNotFoundError("MCP token not found.")
        return await self._repository.save(replace(token, is_deleted=True))
