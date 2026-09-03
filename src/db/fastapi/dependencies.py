from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import get_async_session

AsyncSessionDepends = Annotated[AsyncSession, Depends(get_async_session)]


__all__ = [
    "AsyncSessionDepends",
]
