from pydantic import BaseModel, Field
from pystructor import omit, partial

from src.modules.user.infra.db_models import UserRecord

common_omit_fields = [
    "id",
    "hashed_password",
    "auth_provider",
    "is_verified",
    "is_active",
    "signed_up_at",
    "last_password_change",
    "password_version"
]


@omit(UserRecord, "role", *common_omit_fields)
class UserCreateSchema(BaseModel):
    """Схема для создания пользователя в БД"""


@omit(UserRecord, *common_omit_fields)
class UserReadSchema(BaseModel):
    """Схема для чтения пользователя с БД"""

    class Config:
        from_attributes = True


@partial(UserCreateSchema)
class UserUpdateSchema(BaseModel):
    """Схема для обновления пользователя в БД"""
