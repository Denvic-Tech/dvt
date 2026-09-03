from typing import Optional
from datetime import datetime
from pydantic import BaseModel

from pystructor import generate_crud_schemas

from src.models.user_tokens import UsersTokenRecord


class UserTokenRead(BaseModel):
    id: str
    token_type: str
    name: Optional[str]
    created_at: datetime
    expires_at: Optional[int]

    model_config = {
        "from_attributes": True
    }

(
    UserTokenCreate,
    _UserTokenRead,
    UserTokenUpdate,
) = generate_crud_schemas(
    UsersTokenRecord
)
