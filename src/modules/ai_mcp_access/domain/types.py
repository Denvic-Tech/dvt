from enum import StrEnum


class ResourceScopeMode(StrEnum):
    ALL = "all"
    SELECTED = "selected"


MCP_TOKEN_TYPE = "MCP"
MCP_TOKEN_PREFIX = "dvt_mcp_"
MCP_SCOPE_SCHEMA_VERSION = 1
