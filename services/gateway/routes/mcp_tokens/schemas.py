from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ResourceScopeSchema(BaseModel):
    mode: Literal["all", "selected"]
    ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_ids(self) -> "ResourceScopeSchema":
        self.ids = sorted({item.strip() for item in self.ids if item.strip()})
        if self.mode == "all" and self.ids:
            raise ValueError("ids must be empty when mode=all")
        return self


class MCPAccessScopeSchema(BaseModel):
    schema_version: Literal[1] = 1
    purpose: Literal["mcp"] = "mcp"
    projects: ResourceScopeSchema
    db_connections: ResourceScopeSchema


class MCPTokenCreateSchema(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    expires_at: int | None = Field(default=None, gt=0)
    access_scope: MCPAccessScopeSchema


class MCPTokenUpdateSchema(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    expires_at: int | None = Field(default=None, gt=0)
    access_scope: MCPAccessScopeSchema | None = None

    @model_validator(mode="after")
    def reject_null_scope(self) -> "MCPTokenUpdateSchema":
        if "access_scope" in self.model_fields_set and self.access_scope is None:
            raise ValueError("access_scope cannot be null")
        return self


class MCPTokenReadSchema(BaseModel):
    id: str
    name: str | None
    created_at: datetime
    expires_at: int | None
    access_scope: MCPAccessScopeSchema


class MCPTokenCreatedSchema(MCPTokenReadSchema):
    token: str = Field(description="Raw MCP token. It is returned only once.")


class MCPTokenListSchema(BaseModel):
    items: list[MCPTokenReadSchema]
