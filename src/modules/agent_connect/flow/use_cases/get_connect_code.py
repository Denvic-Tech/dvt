from __future__ import annotations

from datetime import UTC, datetime

from ...domain.entities import AgentConnectCode
from ...domain.exceptions import ConnectCodeNotFoundError
from ...domain.policies import digest_code, ensure_readable
from ...domain.repositories import AgentConnectCodeRepository


class GetConnectCode:
    """Resolve a public code to its request without claiming it (used to render the instruction)."""

    def __init__(self, repository: AgentConnectCodeRepository) -> None:
        self._repository = repository

    async def execute(self, *, raw_code: str, now: datetime | None = None) -> AgentConnectCode:
        code = await self._repository.get_by_digest(digest_code(raw_code))
        if code is None:
            raise ConnectCodeNotFoundError("Connection link not found.")
        ensure_readable(code, now or datetime.now(UTC))
        return code
