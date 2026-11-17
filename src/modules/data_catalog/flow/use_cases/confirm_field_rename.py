from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from ...domain import (
    CatalogViewer,
    DatasetField,
    DatasetFieldRepository,
    DatasetNotFoundError,
    DatasetRepository,
    FieldRef,
    FieldRenameNotApplicableError,
    FieldStatus,
)
from ...domain.policies import resolve_field

_RENAME_TARGET_STATUSES = frozenset({FieldStatus.NEW, FieldStatus.OK, FieldStatus.TYPE_CHANGED})


class ConfirmFieldRename:
    """Переносит идентичность пропавшего поля на новое: старая строка получает новое имя."""

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
        missing: FieldRef,
        new: FieldRef,
    ) -> DatasetField:
        dataset = await self._datasets.get_visible(dataset_id, viewer)
        if dataset is None:
            raise DatasetNotFoundError(f"Dataset {dataset_id} is not visible")

        existing = await self._fields.list_for_dataset(dataset.id)
        old_field = resolve_field(existing, missing)
        new_field = resolve_field(existing, new)

        if old_field.id == new_field.id:
            raise FieldRenameNotApplicableError("Missing and new fields must differ.")
        if old_field.status is not FieldStatus.MISSING:
            raise FieldRenameNotApplicableError(
                f"Field {old_field.name!r} is not missing; nothing to rename."
            )
        if new_field.status not in _RENAME_TARGET_STATUSES:
            raise FieldRenameNotApplicableError(
                f"Field {new_field.name!r} has status {new_field.status.value!r} "
                "and cannot be a rename target."
            )

        # Сначала удаляем новую строку: UPDATE имени раньше DELETE нарушил бы уникальность имени.
        await self._fields.delete(new_field.id)

        now = self._clock()
        old_field.name = new_field.name
        old_field.dtype = new_field.dtype
        old_field.nullable = new_field.nullable
        old_field.ordinal = new_field.ordinal
        old_field.primary_key = new_field.primary_key
        old_field.source_comment = new_field.source_comment
        old_field.last_seen_at = new_field.last_seen_at
        old_field.status = FieldStatus.OK
        old_field.observed_via = tuple(
            dict.fromkeys((*old_field.observed_via, *new_field.observed_via))
        )
        if not old_field.description and new_field.description:
            old_field.description = new_field.description
            old_field.description_updated_by = new_field.description_updated_by
            old_field.description_updated_at = new_field.description_updated_at
        await self._fields.save_many([old_field])

        dataset.updated_at = now
        await self._datasets.update(dataset)
        return old_field
