from typing import Optional

from pydantic import BaseModel, EmailStr, Field
from pystructor import omit

from src.enums import DVTDefaultRoles
from src.modules.user.infra.db_models import UserRecord


class AdminUserCreateSchema(BaseModel):
    """Схема для создания пользователя в БД"""
    email: EmailStr = Field(..., title="Email пользователя")
    user_name: str = Field(..., title="Имя пользователя")
    password: str = Field(..., title="Пароль пользователя")
    role: DVTDefaultRoles = Field(DVTDefaultRoles.USER, title="Роль пользователя")
    organization_id: Optional[str] = Field(default=None, title="ID организации пользователя")


@omit(UserRecord, "hashed_password", )
class AdminUserReadSchema(BaseModel):

    class Config:
        from_attributes = True


class AdminUserUpdateSchema(BaseModel):
    user_id: str
    email: Optional[EmailStr] = None
    user_name: Optional[str] = None
    password: Optional[str] = None
    role: Optional[DVTDefaultRoles] = None
    is_active: Optional[bool] = None
    is_verified: Optional[bool] = None
    organization_id: Optional[str] = None
