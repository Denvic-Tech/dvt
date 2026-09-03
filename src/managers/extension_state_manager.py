from __future__ import annotations

import hashlib
import threading
from collections.abc import Callable
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, TypeVar

from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import Session

from src.db import get_async_session_acm, engine
from src.models.extension import ExtensionRecord

TState = TypeVar("TState", bound=dict[str, Any])


class ExtensionStateManager:
    _local_locks_guard = threading.Lock()
    _local_locks: dict[tuple[str, str], threading.RLock] = {}

    @classmethod
    def _get_local_lock(cls, extension_name: str, key: str) -> threading.RLock:
        lock_key = (extension_name, key)
        with cls._local_locks_guard:
            lock = cls._local_locks.get(lock_key)
            if lock is None:
                lock = threading.RLock()
                cls._local_locks[lock_key] = lock
            return lock

    @staticmethod
    def _advisory_lock_key(extension_name: str, key: str) -> int:
        raw_key = f"{extension_name}:{key}".encode("utf-8")
        digest = hashlib.blake2b(raw_key, digest_size=8).digest()
        value = int.from_bytes(digest, byteorder="big", signed=False)
        if value >= 2 ** 63:
            value -= 2 ** 64
        return value

    @staticmethod
    def _is_postgres_bind(bind: Engine | Any | None) -> bool:
        return bind is not None and getattr(getattr(bind, "dialect", None), "name", None) == "postgresql"

    @classmethod
    @contextmanager
    def _sync_lock_context(
        cls,
        session: Session,
        extension_name: str,
        key: str,
    ):
        bind = session.get_bind()
        if cls._is_postgres_bind(bind):
            session.execute(
                text("SELECT pg_advisory_xact_lock(:lock_key)"),
                {"lock_key": cls._advisory_lock_key(extension_name, key)},
            )
        yield

    @classmethod
    async def _async_lock(
        cls,
        session: AsyncSession,
        extension_name: str,
        key: str,
    ) -> None:
        bind = session.get_bind()
        if cls._is_postgres_bind(bind):
            await session.execute(
                text("SELECT pg_advisory_xact_lock(:lock_key)"),
                {"lock_key": cls._advisory_lock_key(extension_name, key)},
            )

    @staticmethod
    def _normalize_state(value: dict[str, Any] | None) -> dict[str, Any]:
        return dict(value or {})

    @classmethod
    def _read_key_state(cls, state_json: dict[str, Any] | None, key: str) -> dict[str, Any]:
        normalized = cls._normalize_state(state_json)
        if key == "default":
            return normalized
        return cls._normalize_state(normalized.get(key))

    @classmethod
    def _write_key_state(
        cls,
        state_json: dict[str, Any] | None,
        key: str,
        value: dict[str, Any],
    ) -> dict[str, Any]:
        normalized = cls._normalize_state(state_json)
        if key == "default":
            return cls._normalize_state(value)
        normalized[key] = cls._normalize_state(value)
        return normalized

    @staticmethod
    def _state_select_stmt(extension_name: str, for_update: bool):
        stmt = select(ExtensionRecord).where(ExtensionRecord.name == extension_name)
        if for_update:
            stmt = stmt.with_for_update()
        return stmt

    @staticmethod
    async def async_get_state(extension_name: str, key: str = "default") -> dict[str, Any]:
        async with get_async_session_acm() as session:
            result = await session.execute(
                select(ExtensionRecord).where(ExtensionRecord.name == extension_name)
            )
            extension = result.scalars().first()
            if extension is None:
                return {}
            return ExtensionStateManager._read_key_state(extension.state_json, key)

    @staticmethod
    async def async_set_state(
        extension_name: str,
        value: dict[str, Any],
        key: str = "default",
    ) -> dict[str, Any]:
        return await ExtensionStateManager.async_update_state(
            extension_name=extension_name,
            updater=lambda _: dict(value),
            key=key,
        )

    @staticmethod
    async def async_update_state(
        extension_name: str,
        updater: Callable[[dict[str, Any]], TState],
        key: str = "default",
    ) -> TState:
        local_lock = ExtensionStateManager._get_local_lock(extension_name, key)
        with local_lock:
            async with get_async_session_acm() as session:
                async with session.begin():
                    await ExtensionStateManager._async_lock(session, extension_name, key)
                    result = await session.execute(
                        ExtensionStateManager._state_select_stmt(
                            extension_name,
                            for_update=ExtensionStateManager._is_postgres_bind(session.get_bind()),
                        )
                    )
                    extension = result.scalars().first()
                    if extension is None:
                        raise ValueError(f"Extension '{extension_name}' not found.")

                    current_state = ExtensionStateManager._read_key_state(extension.state_json, key)
                    next_state = ExtensionStateManager._normalize_state(updater(current_state))
                    extension.state_json = ExtensionStateManager._write_key_state(
                        extension.state_json,
                        key,
                        next_state,
                    )
                    extension.updated_at = datetime.now(UTC)
                    session.add(extension)
                    return next_state

    @staticmethod
    def get_state(extension_name: str, key: str = "default") -> dict[str, Any]:
        with Session(engine) as session:
            extension = session.exec(
                select(ExtensionRecord).where(ExtensionRecord.name == extension_name)
            ).scalars().first()
            if extension is None:
                return {}
            return ExtensionStateManager._read_key_state(extension.state_json, key)

    @staticmethod
    def set_state(extension_name: str, value: dict[str, Any], key: str = "default") -> dict[str, Any]:
        return ExtensionStateManager.update_state(
            extension_name=extension_name,
            updater=lambda _: dict(value),
            key=key,
        )

    @staticmethod
    def update_state(
        extension_name: str,
        updater: Callable[[dict[str, Any]], TState],
        key: str = "default",
    ) -> TState:
        local_lock = ExtensionStateManager._get_local_lock(extension_name, key)
        with local_lock:
            with Session(engine) as session:
                with session.begin():
                    with ExtensionStateManager._sync_lock_context(session, extension_name, key):
                        extension = session.exec(
                            ExtensionStateManager._state_select_stmt(
                                extension_name,
                                for_update=ExtensionStateManager._is_postgres_bind(session.get_bind()),
                            )
                        ).scalars().first()
                        if extension is None:
                            raise ValueError(f"Extension '{extension_name}' not found.")

                        current_state = ExtensionStateManager._read_key_state(extension.state_json, key)
                        next_state = ExtensionStateManager._normalize_state(updater(current_state))
                        extension.state_json = ExtensionStateManager._write_key_state(
                            extension.state_json,
                            key,
                            next_state,
                        )
                        extension.updated_at = datetime.now(UTC)
                        session.add(extension)
                        return next_state
