from __future__ import annotations

import hashlib
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.schema import CreateSchema, DropSchema

from src.db import async_engine

_PG_IDENTIFIER_MAX_LENGTH = 63
_SIMPLE_NAME_RE = re.compile(r"^[a-z0-9_]+$")


def extension_schema_name(extension_name: str) -> str:
    """Return the deterministic host-owned PostgreSQL schema for an extension."""
    raw_name = (extension_name or "").strip()
    if not raw_name:
        raise ValueError("Extension name cannot be empty")

    canonical = raw_name.lower()
    slug = re.sub(r"[^a-z0-9_]+", "_", canonical).strip("_") or "extension"
    prefix = "dvt_ext_"
    digest = hashlib.sha256(raw_name.encode("utf-8")).hexdigest()[:8]
    needs_hash = raw_name != canonical or not _SIMPLE_NAME_RE.fullmatch(canonical)
    suffix = f"_{digest}" if needs_hash else ""
    available = _PG_IDENTIFIER_MAX_LENGTH - len(prefix) - len(suffix)
    if len(slug) > available:
        suffix = f"_{digest}"
        available = _PG_IDENTIFIER_MAX_LENGTH - len(prefix) - len(suffix)
        slug = slug[:available].rstrip("_") or "extension"
    return f"{prefix}{slug}{suffix}"


def _quoted_search_path(schema_name: str, dialect) -> str:
    quoted = dialect.identifier_preparer.quote(schema_name)
    return f"{quoted}, public"


@asynccontextmanager
async def extension_async_session(
    extension_name: str,
    *,
    _engine: AsyncEngine | None = None,
) -> AsyncIterator[AsyncSession]:
    """Open an async session whose every transaction uses extension_schema, public.

    ``SET LOCAL`` is transaction-scoped, so a pooled connection cannot leak the
    extension search_path into a later core request. The ``after_begin`` hook is
    invoked again after both commit and rollback when a new transaction starts.
    """
    schema_name = extension_schema_name(extension_name)
    engine = _engine or async_engine
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    session = session_factory()

    def _set_search_path(_session, _transaction, connection) -> None:
        search_path = _quoted_search_path(schema_name, connection.dialect)
        connection.exec_driver_sql(f"SET LOCAL search_path TO {search_path}")

    event.listen(session.sync_session, "after_begin", _set_search_path)
    try:
        yield session
    finally:
        event.remove(session.sync_session, "after_begin", _set_search_path)
        await session.close()


async def ensure_extension_schema(
    extension_name: str, *, _engine: AsyncEngine | None = None
) -> str:
    schema_name = extension_schema_name(extension_name)
    engine = _engine or async_engine
    async with engine.begin() as connection:
        await connection.execute(CreateSchema(schema_name, if_not_exists=True))
    return schema_name


async def drop_extension_schema(
    extension_name: str, *, _engine: AsyncEngine | None = None
) -> None:
    schema_name = extension_schema_name(extension_name)
    engine = _engine or async_engine
    async with engine.begin() as connection:
        await connection.execute(DropSchema(schema_name, cascade=True, if_exists=True))


__all__ = [
    "drop_extension_schema",
    "ensure_extension_schema",
    "extension_async_session",
    "extension_schema_name",
]
