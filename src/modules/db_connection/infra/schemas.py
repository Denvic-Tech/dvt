from db_connection import (
    ConnectionCreateRequest as DefaultConnectionCreateRequest,
    ConnectionReadResponse as DefaultConnectionReadResponse,
    ConnectionUpdateRequest as DefaultConnectionUpdateRequest,
)
from pydantic import Field


class DVTConnectionCreateRequest(DefaultConnectionCreateRequest):
    user_id: str | None = Field(None, description="ID пользователя, которому принадлежит соединение")
    organization_id: str | None = Field(None, description="ID организации, которой принадлежит соединение")


class DVTConnectionReadRequest(DefaultConnectionReadResponse):
    user_id: str | None = Field(..., description="ID пользователя, которому принадлежит соединение")
    organization_id: str | None = Field(..., description="ID организации, которой принадлежит соединение")


class DVTConnectionUpdateRequest(DefaultConnectionUpdateRequest):
    user_id: str | None = Field(None, description="ID пользователя, которому принадлежит соединение")
    organization_id: str | None = Field(None, description="ID организации, которой принадлежит соединение")
