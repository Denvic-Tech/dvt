from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.db_connection.infra.db_models import DVTStoredConnectionRecord

from ...domain import CatalogViewer, DatasetConnection, DatasetConnectionRepository
from ..catalog_mappers import connection_to_domain
from ..db_models import DatasetConnectionRecord
from .visibility import connection_visibility_filters


class SQLAlchemyDatasetConnectionRepository(DatasetConnectionRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def touch(
        self,
        dataset_id: str,
        connection_id: str,
        revision: str,
        seen_at: datetime,
    ) -> None:
        record = await self._session.get(DatasetConnectionRecord, (dataset_id, connection_id))
        if record is not None:
            record.connection_revision = revision
            record.last_seen_at = seen_at
            await self._session.flush()
            return

        try:
            async with self._session.begin_nested():
                self._session.add(
                    DatasetConnectionRecord(
                        dataset_id=dataset_id,
                        connection_id=connection_id,
                        connection_revision=revision,
                        first_seen_at=seen_at,
                        last_seen_at=seen_at,
                    )
                )
                await self._session.flush()
        except IntegrityError:
            record = await self._session.get(DatasetConnectionRecord, (dataset_id, connection_id))
            if record is None:
                raise
            record.connection_revision = revision
            record.last_seen_at = seen_at
            await self._session.flush()

    async def list_for_dataset(self, dataset_id: str) -> list[DatasetConnection]:
        statement = (
            sa.select(DatasetConnectionRecord)
            .where(DatasetConnectionRecord.dataset_id == dataset_id)
            .order_by(DatasetConnectionRecord.last_seen_at.desc())
        )
        records = (await self._session.execute(statement)).scalars().all()
        return [connection_to_domain(record) for record in records]

    async def list_usable_connection_ids(self, dataset_id: str, viewer: CatalogViewer) -> list[str]:
        statement = (
            sa.select(DatasetConnectionRecord.connection_id)
            .join(
                DVTStoredConnectionRecord,
                DVTStoredConnectionRecord.id == DatasetConnectionRecord.connection_id,
            )
            .where(
                DatasetConnectionRecord.dataset_id == dataset_id,
                *connection_visibility_filters(viewer),
            )
            .order_by(DatasetConnectionRecord.last_seen_at.desc())
        )
        return list((await self._session.execute(statement)).scalars().all())
