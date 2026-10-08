from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.db_connection.infra.db_models import DVTStoredConnectionRecord

from ...domain import ConnectionLocator, ConnectionLocatorGateway


def _as_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


class SQLConnectionLocatorGateway(ConnectionLocatorGateway):
    """Читает несекретные координаты connection'а напрямую из connections_v1."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_locator(self, connection_id: str, organization_id: str) -> ConnectionLocator | None:
        statement = sa.select(DVTStoredConnectionRecord).where(
            DVTStoredConnectionRecord.id == connection_id,
            DVTStoredConnectionRecord.organization_id == organization_id,
        )
        record = (await self._session.execute(statement)).scalar_one_or_none()
        if record is None:
            return None

        properties: dict[str, Any] = dict(record.properties_json or {})
        host = _as_str(properties.get("host")) or ""
        port = _as_int(properties.get("port"))
        instance_name = _as_str(properties.get("instance_name"))
        if instance_name and port is None:
            host = f"{host}\\{instance_name}"

        updated_at = getattr(record, "updated_at", None)
        revision = updated_at.isoformat() if updated_at is not None else "unversioned"

        return ConnectionLocator(
            id=record.id,
            dialect=str(record.type or "").strip().lower(),
            host=host,
            port=port,
            database=_as_str(properties.get("database")),
            revision=revision,
            deleted=getattr(record, "deleted_at", None) is not None,
        )
