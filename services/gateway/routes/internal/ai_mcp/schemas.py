from typing import Any

from pydantic import BaseModel, Field


class ToolCallSchema(BaseModel):
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolResultSchema(BaseModel):
    result: Any


class AuthVerificationSchema(BaseModel):
    user_id: str
    token_id: str
    access_scope: dict[str, Any]
