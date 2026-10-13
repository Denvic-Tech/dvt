from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from ...domain import (
    CatalogViewer,
    DatasetConnectionRepository,
    DatasetDetails,
    DatasetFieldRepository,
    DatasetNotFoundError,
    DatasetRepository,
    SchemaActor,
)
from ...domain.policies import compute_freshness
from .sync_dataset_schema import SyncDatasetSchema


class GetDataset:
    def __init__(
        self,
        *,
        datasets: DatasetRepository,
        fields: DatasetFieldRepository,
        connections: DatasetConnectionRepository,
        ttl_seconds: int,
        sync_schema: SyncDatasetSchema | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._datasets = datasets
        self._fields = fields
        self._connections = connections
        self._ttl = ttl_seconds
        self._sync = sync_schema
        self._clock = clock or (lambda: datetime.now(UTC))

    async def execute(
        self,
        *,
        dataset_id: str,
        viewer: CatalogViewer,
        actor: SchemaActor | None = None,
        include_fields: bool = True,
        sync: bool = True,
    ) -> DatasetDetails:
        dataset = await self._datasets.get_visible(dataset_id, viewer)
        if dataset is None:
            raise DatasetNotFoundError(f"Dataset {dataset_id} is not visible")

        if include_fields and sync and self._sync is not None and actor is not None:
            await self._sync.execute(dataset=dataset, viewer=viewer, actor=actor)

        fields = tuple(await self._fields.list_for_dataset(dataset.id)) if include_fields else ()
        connection_ids = tuple(
            item.connection_id for item in await self._connections.list_for_dataset(dataset.id)
        )
        return DatasetDetails(
            dataset=dataset,
            freshness=compute_freshness(dataset, ttl_seconds=self._ttl, now=self._clock()),
            fields=fields,
            connection_ids=connection_ids,
        )
