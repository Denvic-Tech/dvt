import sqlalchemy as sa
from sqlmodel.ext.asyncio.session import AsyncSession

from src.modules.extension_management.domain.entities import Extension
from src.modules.extension_management.infra.db_models import ExtensionRecord
from src.modules.extension_management.infra.identity import resolve_record
from src.modules.extension_management.infra.mappers import extension_record_to_domain


class SQLExtensionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list(self) -> list[Extension]:
        result = await self._session.execute(
            sa.select(ExtensionRecord).order_by(ExtensionRecord.name)
        )
        return [extension_record_to_domain(item) for item in result.scalars().all()]

    async def get(self, name: str) -> Extension | None:
        result = await self._session.execute(
            sa.select(ExtensionRecord)
        )
        record = resolve_record(result.scalars().all(), name)
        return extension_record_to_domain(record) if record is not None else None


__all__ = ["SQLExtensionRepository"]
