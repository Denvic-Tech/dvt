from dataclasses import dataclass
from datetime import datetime

from .value_objects import MCPAccessScope


@dataclass(frozen=True, slots=True)
class MCPToken:
    id: str
    user_id: str
    token_digest: str
    name: str | None
    access_scope: MCPAccessScope
    created_at: datetime
    expires_at: int | None = None
    is_deleted: bool = False
