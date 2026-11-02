from datetime import datetime

from pydantic import BaseModel, Field

from services.gateway.routes.mcp_tokens.schemas import MCPAccessScopeSchema

from src.modules.agent_connect.domain import ConnectCodeStatus


class ConnectLinkCreateSchema(BaseModel):
    base_url: str = Field(
        max_length=2048,
        description=(
            "Origin the user opened DVT from (window.location.origin); must be one of the "
            "public addresses of this installation. Links in the instruction are built from it"
        ),
    )
    access_scope: MCPAccessScopeSchema
    name: str | None = Field(default=None, max_length=255, description="Name of the MCP token")
    token_expires_at: int | None = Field(
        default=None,
        gt=0,
        description="Unix time when the issued MCP token expires; null for no expiry",
    )


class ConnectLinkCreatedSchema(BaseModel):
    id: str
    code: str = Field(description="One-time code; shown only in this response")
    connect_url: str = Field(description="Link to the agent instruction; give it to the agent")
    expires_at: datetime


class ConnectLinkReadSchema(BaseModel):
    id: str
    created_at: datetime
    expires_at: datetime
    status: ConnectCodeStatus
    claims_count: int
    token_id: str | None
    last_claimed_at: datetime | None


class ConnectLinkListSchema(BaseModel):
    items: list[ConnectLinkReadSchema]
