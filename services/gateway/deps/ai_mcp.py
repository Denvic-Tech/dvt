from fastapi import HTTPException, status

import config


def require_ai_mcp_enabled() -> None:
    if not config.AI_MCP.ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI MCP is disabled.",
        )


__all__ = ["require_ai_mcp_enabled"]
