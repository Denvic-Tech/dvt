from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from ...domain import DatasetField, DatasetFieldRepository
from ..catalog_mappers import apply_field, field_to_domain, field_to_record
from ..db_models import DatasetFieldRecord


class SQLAlchemyDatasetFieldRepository(DatasetFieldRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_dataset(self, dataset_id: str) -> list[DatasetField]:
        statement = (
            sa.select(DatasetFieldRecord)
            .where(DatasetFieldRecord.dataset_id == dataset_id)
            .order_by(
                DatasetFieldRecord.ordinal.is_(None),
                DatasetFieldRecord.ordinal,
                DatasetFieldRecord.name,
            )
        )
        records = (await self._session.execute(statement)).scalars().all()
        return [field_to_domain(record) for record in records]

    async def save_many(self, fields: Sequence[DatasetField]) -> None:
        if not fields:
            return
        ids = [field.id for field in fields]
        existing = {
            record.id: record
            for record in (
                await self._session.execute(
                    sa.select(DatasetFieldRecord).where(DatasetFieldRecord.id.in_(ids))
                )
            ).scalars()
        }
        for field in fields:
            record = existing.get(field.id)
            if record is None:
                self._session.add(field_to_record(field))
            else:
                apply_field(record, field)
        await self._session.flush()

    async def delete(self, field_id: str) -> None:
        # Единственное физическое удаление в каталоге: после подтверждения переименования
        # новая строка является дубликатом наблюдения, идентичность остаётся у старой.
        # ORM-удаление с flush держит identity map согласованной со строками, уже
        # загруженными list_for_dataset в этой же транзакции, и освобождает имя до UPDATE.
        record = await self._session.get(DatasetFieldRecord, field_id)
        if record is None:
            return
        await self._session.delete(record)
        await self._session.flush()
