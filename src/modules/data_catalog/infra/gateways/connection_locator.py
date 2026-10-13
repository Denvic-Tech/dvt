from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.db_connection.infra.db_models import DVTStoredConnectionRecord

from ...domain import ConnectionLocator, ConnectionLocatorGateway

_SENSITIVE_KEY_MARKERS = ("password", "secret", "token", "key", "credential")


def _is_sensitive(name: str) -> bool:
    lowered = name.lower()
    return any(marker in lowered for marker in _SENSITIVE_KEY_MARKERS)


def public_connection_properties(properties: Any) -> dict[str, Any]:
    """Свойства connection'а без секретоподобных ключей; адаптеры видов читают из них координаты."""
    if not isinstance(properties, dict):
        return {}
    return {
        str(name): value
        for name, value in properties.items()
        if not _is_sensitive(str(name))
    }


class SQLConnectionLocatorGateway(ConnectionLocatorGateway):
    """Читает несекретные свойства сохранённого connection'а напрямую из connections_v1."""

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

        updated_at = getattr(record, "updated_at", None)
        revision = updated_at.isoformat() if updated_at is not None else "unversioned"

        return ConnectionLocator(
            id=record.id,
            type=str(record.type or "").strip().lower(),
            revision=revision,
            deleted=getattr(record, "deleted_at", None) is not None,
            properties=public_connection_properties(record.properties_json),
        )
