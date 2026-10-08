from __future__ import annotations

from collections.abc import Sequence

from ..catalog_values import FieldRef
from ..entities import DatasetField
from ..exceptions import DatasetFieldNotFoundError


def resolve_field(fields: Sequence[DatasetField], ref: FieldRef) -> DatasetField:
    for field in fields:
        if ref.field_id is not None and field.id == ref.field_id:
            return field
        if ref.name is not None and field.name == ref.name:
            return field
    label = ref.field_id if ref.field_id is not None else ref.name
    raise DatasetFieldNotFoundError(f"Field {label!r} was not found in the dataset.")
