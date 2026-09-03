from dataclasses import replace

from ...domain.entities import MCPToken
from ...domain.exceptions import MCPTokenNotFoundError
from ...domain.repositories import MCPTokenRepository
from ...domain.value_objects import MCPAccessScope


class UpdateMCPToken:
    def __init__(self, repository: MCPTokenRepository) -> None:
        self._repository = repository

    async def execute(
        self,
        *,
        token_id: str,
        user_id: str,
        update_name: bool = False,
        name: str | None = None,
        update_expires_at: bool = False,
        expires_at: int | None = None,
        update_access_scope: bool = False,
        access_scope: MCPAccessScope | None = None,
    ) -> MCPToken:
        token = await self._repository.get_for_user(token_id, user_id)
        if token is None:
            raise MCPTokenNotFoundError("MCP token not found.")
        updated = replace(
            token,
            name=(name.strip() if name else None) if update_name else token.name,
            expires_at=expires_at if update_expires_at else token.expires_at,
            access_scope=(
                access_scope
                if update_access_scope and access_scope is not None
                else token.access_scope
            ),
        )
        return await self._repository.save(updated)
