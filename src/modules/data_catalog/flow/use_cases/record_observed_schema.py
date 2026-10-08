from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

from src.logger import logger

from ...domain import (
    DatasetConnectionRepository,
    DatasetFieldRepository,
    DatasetLinkRepository,
    DatasetRepository,
    LinkDirection,
    ObservationOutcome,
    ObservedNodeSchema,
)
from ...domain.policies import merge_observed_fields


class RecordObservedSchema:
    """Обновляет поля уже зарегистрированных сущностей по схеме, наблюдённой при прогоне."""

    def __init__(
        self,
        *,
        datasets: DatasetRepository,
        fields: DatasetFieldRepository,
        connections: DatasetConnectionRepository,
        links: DatasetLinkRepository,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._datasets = datasets
        self._fields = fields
        self._connections = connections
        self._links = links
        self._new_id = id_factory or (lambda: str(uuid4()))

    async def execute(self, observation: ObservedNodeSchema) -> ObservationOutcome:
        dataset_ids = await self._links.find_dataset_ids(
            observation.project_id, observation.node_id, LinkDirection.READ
        )
        if not dataset_ids:
            return ObservationOutcome()

        updated: list[str] = []
        for dataset_id in dataset_ids:
            dataset = await self._datasets.get(dataset_id)
            if dataset is None:
                continue
            if (
                observation.table is not None
                and dataset.locator.table.lower() != observation.table.lower()
            ):
                logger.debug(
                    "Observed table {} does not match dataset {} ({}); skipping",
                    observation.table,
                    dataset.id,
                    dataset.locator.table,
                )
                continue

            existing = await self._fields.list_for_dataset(dataset.id)
            merged = merge_observed_fields(
                dataset_id=dataset.id,
                existing=existing,
                observed=observation.fields,
                connection_id=observation.connection_id,
                now=observation.observed_at,
                new_id=self._new_id,
                update_types=observation.trust_types,
                mark_missing=not observation.partial,
            )
            await self._fields.save_many(merged)
            await self._connections.touch(
                dataset.id,
                observation.connection_id,
                observation.connection_revision,
                observation.observed_at,
            )

            dataset.observed_at_run = observation.observed_at
            if observation.trust_types and not observation.partial:
                dataset.schema_synced_at = observation.observed_at
            dataset.updated_at = observation.observed_at
            await self._datasets.update(dataset)
            updated.append(dataset.id)

        return ObservationOutcome(dataset_ids=tuple(updated), trusted_types=observation.trust_types)
