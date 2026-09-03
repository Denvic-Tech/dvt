from ...domain.entities import MCPToken
from ...domain.exceptions import InvalidMCPTokenError
from ...domain.policies import parse_token_id, verify_token
from ...domain.repositories import MCPTokenRepository


class AuthenticateMCPToken:
    def __init__(self, repository: MCPTokenRepository) -> None:
        self._repository = repository

    async def execute(self, *, raw_token: str) -> MCPToken:
        token_id = parse_token_id(raw_token)
        token = await self._repository.get_by_id(token_id)
        if token is None:
            raise InvalidMCPTokenError("Invalid MCP token.")
        verify_token(token, raw_token)
        return token
