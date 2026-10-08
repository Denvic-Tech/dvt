from __future__ import annotations

from ...domain import (
    CatalogViewer,
    DatasetLinkRepository,
    DatasetNotFoundError,
    DatasetRepository,
    RefreshOutcome,
    SchemaActor,
)
from .sync_dataset_schema import SyncDatasetSchema


class RefreshDatasetSchema:
    """Принудительное чтение схемы из источника с обходом кэша db_catalog."""

    def __init__(
        self,
        *,
        datasets: DatasetRepository,
        links: DatasetLinkRepository,
        sync_schema: SyncDatasetSchema,
    ) -> None:
        self._datasets = datasets
        self._links = links
        self._sync = sync_schema

    async def execute(
        self,
        *,
        dataset_id: str,
        viewer: CatalogViewer,
        actor: SchemaActor,
    ) -> RefreshOutcome:
        dataset = await self._datasets.get_visible(dataset_id, viewer)
        if dataset is None:
            raise DatasetNotFoundError(f"Dataset {dataset_id} is not visible")

        outcome = await self._sync.execute(
            dataset=dataset,
            viewer=viewer,
            actor=actor,
            force=True,
            bypass_cache=True,
        )
        if outcome.status == "no_connection":
            return RefreshOutcome(status="no_connection")
        if outcome.status == "failed":
            return RefreshOutcome(
                status="failed", error=outcome.error, error_kind=outcome.error_kind
            )

        affected = await self._links.list_project_ids(dataset.id, viewer)
        return RefreshOutcome(
            status="synced",
            new=outcome.new,
            missing=outcome.missing,
            type_changed=outcome.type_changed,
            affected_project_ids=tuple(affected),
        )
