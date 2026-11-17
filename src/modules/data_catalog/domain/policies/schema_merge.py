"""Слияние наблюдённой схемы с сохранёнными полями: ничего не удаляем, только помечаем."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime

from ..catalog_values import ObservedField
from ..entities import DatasetField
from ..types import FieldStatus


def merge_observed_fields(
    *,
    dataset_id: str,
    existing: Sequence[DatasetField],
    observed: Sequence[ObservedField],
    connection_id: str,
    now: datetime,
    new_id: Callable[[], str],
    update_types: bool = True,
    mark_missing: bool = True,
) -> list[DatasetField]:
    """Возвращает полный список полей после слияния.

    update_types=False (наблюдение из FULL-прогона, типы pandas): меняются только состав,
    комментарий, observed_via и last_seen_at; dtype/nullable/primary_key и статус type_changed
    не трогаются, missing возвращается в ok.
    mark_missing=False (нода читала подмножество колонок): отсутствующие поля не помечаются.
    """
    by_name = {field.name: field for field in existing}
    observed_names: set[str] = set()
    result: list[DatasetField] = []

    for column in observed:
        observed_names.add(column.name)
        current = by_name.get(column.name)
        if current is None:
            result.append(
                DatasetField(
                    id=new_id(),
                    dataset_id=dataset_id,
                    name=column.name,
                    status=FieldStatus.NEW,
                    first_seen_at=now,
                    last_seen_at=now,
                    dtype=column.dtype if update_types else None,
                    nullable=column.nullable if update_types else None,
                    ordinal=column.ordinal if update_types else None,
                    primary_key=column.primary_key if update_types else False,
                    source_comment=column.comment,
                    observed_via=(connection_id,),
                )
            )
            continue

        if update_types:
            type_changed = _dtype_differs(current.dtype, column.dtype)
            current.status = FieldStatus.TYPE_CHANGED if type_changed else FieldStatus.OK
            current.dtype = column.dtype
            current.nullable = column.nullable
            current.ordinal = column.ordinal
            current.primary_key = column.primary_key
        elif current.status is FieldStatus.MISSING:
            current.status = FieldStatus.OK
        current.source_comment = column.comment
        current.last_seen_at = now
        if connection_id not in current.observed_via:
            current.observed_via = (*current.observed_via, connection_id)
        result.append(current)

    for field in existing:
        if field.name in observed_names:
            continue
        if mark_missing:
            field.status = FieldStatus.MISSING
        result.append(field)

    return result


def _dtype_differs(previous: str | None, current: str | None) -> bool:
    if previous is None or current is None:
        return False
    return previous.strip().lower() != current.strip().lower()
