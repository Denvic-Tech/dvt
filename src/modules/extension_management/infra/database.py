from __future__ import annotations

import hashlib
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from src.db import async_engine, engine as default_engine
from src.modules.extension_management.infra.db_models import ExtensionRecord
from src.modules.extension_management.infra.identity import resolve_record

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


def resolve_storage_schema(extension_name: str, *, _engine=None) -> str:
    """Resolve aliases to the persisted physical schema, never derive it from an alias."""
    with Session(_engine or default_engine) as session:
        record = resolve_record(session.scalars(select(ExtensionRecord)).all(), extension_name)
        if record is None:
            raise ValueError(f"Extension '{extension_name}' not found")
        return record.storage_schema or extension_schema_name(record.name)


async def _resolve_storage_schema_async(extension_name: str, engine: AsyncEngine) -> str:
    async with AsyncSession(engine) as lookup:
        records = (await lookup.execute(select(ExtensionRecord))).scalars().all()
        record = resolve_record(records, extension_name)
        if record is None:
            raise ValueError(f"Extension '{extension_name}' not found")
        return record.storage_schema or extension_schema_name(record.name)


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
    engine = _engine or async_engine
    schema_name = await _resolve_storage_schema_async(extension_name, engine)
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
    engine = _engine or async_engine
    schema_name = await _resolve_storage_schema_async(extension_name, engine)
    async with engine.begin() as connection:
        await connection.execute(CreateSchema(schema_name, if_not_exists=True))
    return schema_name


async def drop_extension_schema(
    extension_name: str, *, _engine: AsyncEngine | None = None
) -> None:
    engine = _engine or async_engine
    schema_name = await _resolve_storage_schema_async(extension_name, engine)
    async with engine.begin() as connection:
        await connection.execute(DropSchema(schema_name, cascade=True, if_exists=True))


__all__ = [
    "drop_extension_schema",
    "ensure_extension_schema",
    "extension_async_session",
    "extension_schema_name",
]
