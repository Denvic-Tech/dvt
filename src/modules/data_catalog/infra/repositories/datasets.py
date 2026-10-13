from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.project.infra.db_models import ProjectRecord

from ...domain import (
    CatalogViewer,
    Dataset,
    DatasetRepository,
    DatasetSearchHit,
    DatasetSearchPage,
    DatasetSearchQuery,
)
from ..catalog_mappers import apply_dataset, dataset_to_domain, dataset_to_record
from ..db_models import (
    DatasetConnectionRecord,
    DatasetFieldRecord,
    DatasetLinkRecord,
    DatasetRecord,
)
from ..pagination import decode_offset_cursor, encode_offset_cursor
from .visibility import dataset_visibility_filters


class SQLAlchemyDatasetRepository(DatasetRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, dataset_id: str) -> Dataset | None:
        record = await self._session.get(DatasetRecord, dataset_id)
        return dataset_to_domain(record) if record is not None else None

    async def get_visible(self, dataset_id: str, viewer: CatalogViewer) -> Dataset | None:
        statement = sa.select(DatasetRecord).where(
            DatasetRecord.id == dataset_id,
            *dataset_visibility_filters(viewer),
        )
        record = (await self._session.execute(statement)).scalar_one_or_none()
        return dataset_to_domain(record) if record is not None else None

    async def get_by_physical_key(self, organization_id: str, physical_key: str) -> Dataset | None:
        record = await self._select_by_key(organization_id, physical_key)
        return dataset_to_domain(record) if record is not None else None

    async def upsert(self, dataset: Dataset) -> Dataset:
        existing = await self._select_by_key(dataset.organization_id, dataset.physical_key)
        if existing is not None:
            return dataset_to_domain(existing)

        try:
            async with self._session.begin_nested():
                self._session.add(dataset_to_record(dataset))
                await self._session.flush()
        except IntegrityError:
            existing = await self._select_by_key(dataset.organization_id, dataset.physical_key)
            if existing is None:
                raise
            return dataset_to_domain(existing)
        return dataset

    async def update(self, dataset: Dataset) -> Dataset:
        record = await self._session.get(DatasetRecord, dataset.id)
        if record is None:
            record = dataset_to_record(dataset)
            self._session.add(record)
        else:
            apply_dataset(record, dataset)
        await self._session.flush()
        return dataset

    async def search(self, viewer: CatalogViewer, query: DatasetSearchQuery) -> DatasetSearchPage:
        filters = list(dataset_visibility_filters(viewer))
        if query.text:
            pattern = f"%{query.text.strip().lower()}%"
            filters.append(
                sa.or_(
                    sa.func.lower(DatasetRecord.physical_key).like(pattern),
                    sa.func.lower(DatasetRecord.location).like(pattern),
                )
            )
        if query.kind:
            filters.append(DatasetRecord.kind == query.kind.strip())
        if query.connection_id:
            filters.append(
                sa.exists().where(
                    DatasetConnectionRecord.dataset_id == DatasetRecord.id,
                    DatasetConnectionRecord.connection_id == query.connection_id,
                )
            )
        if query.project_id:
            filters.append(
                sa.exists().where(
                    DatasetLinkRecord.dataset_id == DatasetRecord.id,
                    DatasetLinkRecord.project_id == query.project_id,
                )
            )

        total = (
            await self._session.execute(
                sa.select(sa.func.count()).select_from(DatasetRecord).where(*filters)
            )
        ).scalar_one()

        offset = decode_offset_cursor(query.cursor)
        limit = max(1, query.limit)

        field_count = (
            sa.select(sa.func.count(DatasetFieldRecord.id))
            .where(DatasetFieldRecord.dataset_id == DatasetRecord.id)
            .correlate(DatasetRecord)
            .scalar_subquery()
        )
        reader_count = self._link_count_subquery("read")
        writer_count = self._link_count_subquery("write")

        statement = (
            sa.select(DatasetRecord, field_count, reader_count, writer_count)
            .where(*filters)
            .order_by(DatasetRecord.physical_key, DatasetRecord.id)
            .offset(offset)
            .limit(limit)
        )
        rows = (await self._session.execute(statement)).all()
        items = tuple(
            DatasetSearchHit(
                dataset=dataset_to_domain(record),
                field_count=int(fields or 0),
                reader_count=int(readers or 0),
                writer_count=int(writers or 0),
            )
            for record, fields, readers, writers in rows
        )
        return DatasetSearchPage(
            items=items,
            next_cursor=encode_offset_cursor(offset + len(items), int(total)),
        )

    async def _select_by_key(self, organization_id: str, physical_key: str) -> DatasetRecord | None:
        statement = sa.select(DatasetRecord).where(
            DatasetRecord.organization_id == organization_id,
            DatasetRecord.physical_key == physical_key,
        )
        return (await self._session.execute(statement)).scalar_one_or_none()

    @staticmethod
    def _link_count_subquery(direction: str):
        return (
            sa.select(sa.func.count(DatasetLinkRecord.id))
            .select_from(DatasetLinkRecord)
            .join(ProjectRecord, ProjectRecord.id == DatasetLinkRecord.project_id)
            .where(
                DatasetLinkRecord.dataset_id == DatasetRecord.id,
                DatasetLinkRecord.direction == direction,
                ProjectRecord.is_deleted.is_(False),
            )
            .correlate(DatasetRecord)
            .scalar_subquery()
        )
