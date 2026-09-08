from typing import Optional, TypeVar, Generic

from sqlmodel import SQLModel, Field


IDType = TypeVar('IDType')


class ModelWithUIID(SQLModel, Generic[IDType], table=False):
    id: Optional[IDType] = Field(primary_key=True)
    ui_id: str = Field(index=True, nullable=False)
