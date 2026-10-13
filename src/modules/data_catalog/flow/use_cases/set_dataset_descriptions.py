from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from ...domain import (
    UNSET,
    CatalogViewer,
    DatasetFieldRepository,
    DatasetNotFoundError,
    DatasetRepository,
    DescriptionsUpdateResult,
    FieldDescriptionChange,
    Unset,
)
from ...domain.policies import normalize_description, resolve_field


class SetDatasetDescriptions:
    """Глобальные описания сущности и её полей; пропуск отличается от явной очистки."""

    def __init__(
        self,
        *,
        datasets: DatasetRepository,
        fields: DatasetFieldRepository,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._datasets = datasets
        self._fields = fields
        self._clock = clock or (lambda: datetime.now(UTC))

    async def execute(
        self,
        *,
        dataset_id: str,
        viewer: CatalogViewer,
        actor_user_id: str,
        description: str | None | Unset = UNSET,
        fields: Sequence[FieldDescriptionChange] = (),
    ) -> DescriptionsUpdateResult:
        dataset = await self._datasets.get_visible(dataset_id, viewer)
        if dataset is None:
            raise DatasetNotFoundError(f"Dataset {dataset_id} is not visible")

        now = self._clock()
        changed_fields = []
        if fields:
            existing = await self._fields.list_for_dataset(dataset.id)
            # Все ссылки резолвятся до первой записи: неизвестное поле отменяет весь запрос.
            resolved = [(resolve_field(existing, change.ref), change) for change in fields]
            for field, change in resolved:
                field.description = normalize_description(change.description)
                field.description_updated_by = actor_user_id
                field.description_updated_at = now
                changed_fields.append(field)
            await self._fields.save_many(changed_fields)

        if description is not UNSET:
            dataset.description = normalize_description(description)
            dataset.description_updated_by = actor_user_id
            dataset.description_updated_at = now
            dataset.updated_at = now
            await self._datasets.update(dataset)

        return DescriptionsUpdateResult(dataset=dataset, fields=tuple(changed_fields))
