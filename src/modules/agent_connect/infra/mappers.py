from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime

from src.modules.ai_mcp_access.domain.value_objects import MCPAccessScope

from ..domain.entities import AgentConnectCode


def code_to_hash(code: AgentConnectCode) -> dict[str, str]:
    """Flatten the entity into the string-only mapping a Valkey hash stores."""
    return {
        "id": code.id,
        "code_digest": code.code_digest,
        "user_id": code.user_id,
        "access_scope": json.dumps(code.access_scope.to_mapping(), separators=(",", ":")),
        "public_url": code.public_url,
        "created_at": code.created_at.isoformat(),
        "expires_at": code.expires_at.isoformat(),
        "token_name": code.token_name or "",
        "token_expires_at": "" if code.token_expires_at is None else str(code.token_expires_at),
        "token_id": code.token_id or "",
        "claims_count": str(code.claims_count),
        "last_claimed_at": "" if code.last_claimed_at is None else code.last_claimed_at.isoformat(),
        "is_revoked": "1" if code.is_revoked else "0",
    }


def hash_to_code(payload: Mapping[bytes | str, bytes | str]) -> AgentConnectCode:
    data = {_text(key): _text(value) for key, value in payload.items()}
    return AgentConnectCode(
        id=data["id"],
        code_digest=data["code_digest"],
        user_id=data["user_id"],
        access_scope=MCPAccessScope.from_mapping(json.loads(data["access_scope"])),
        public_url=data["public_url"],
        created_at=datetime.fromisoformat(data["created_at"]),
        expires_at=datetime.fromisoformat(data["expires_at"]),
        token_name=data.get("token_name") or None,
        token_expires_at=int(data["token_expires_at"]) if data.get("token_expires_at") else None,
        token_id=data.get("token_id") or None,
        claims_count=int(data.get("claims_count") or 0),
        last_claimed_at=(
            datetime.fromisoformat(data["last_claimed_at"]) if data.get("last_claimed_at") else None
        ),
        is_revoked=data.get("is_revoked") == "1",
    )


def _text(value: bytes | str) -> str:
    return value.decode("utf-8") if isinstance(value, bytes) else value
