class MCPAccessError(Exception):
    """Base error for MCP access-token rules."""


class InvalidAccessScopeError(MCPAccessError):
    pass


class InvalidMCPTokenError(MCPAccessError):
    pass


class ExpiredMCPTokenError(MCPAccessError):
    pass


class RevokedMCPTokenError(MCPAccessError):
    pass


class MCPTokenNotFoundError(MCPAccessError):
    pass
