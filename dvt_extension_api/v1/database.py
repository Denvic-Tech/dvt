"""Async service-PostgreSQL access for extensions."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.extensions.database import extension_async_session, extension_schema_name


def get_extension_schema_name(extension_name: str) -> str:
    return extension_schema_name(extension_name)


async def _extension_session_dependency(request: Request) -> AsyncIterator[AsyncSession]:
    extension_name = request.scope.get("dvt_extension_name")
    if not isinstance(extension_name, str) or not extension_name:
        raise RuntimeError("Extension DB session can only be used from an extension route")
    async with extension_async_session(extension_name) as session:
        yield session


ExtensionAsyncSessionDep = Annotated[AsyncSession, Depends(_extension_session_dependency)]

__all__ = [
    "ExtensionAsyncSessionDep",
    "extension_async_session",
    "get_extension_schema_name",
]
