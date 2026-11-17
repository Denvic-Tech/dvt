from ...domain.entities import AgentConnectCode
from ...domain.repositories import AgentConnectCodeRepository


class ListConnectCodes:
    def __init__(self, repository: AgentConnectCodeRepository) -> None:
        self._repository = repository

    async def execute(self, *, user_id: str) -> list[AgentConnectCode]:
        codes = await self._repository.list_for_user(user_id)
        return sorted(codes, key=lambda code: code.created_at, reverse=True)
