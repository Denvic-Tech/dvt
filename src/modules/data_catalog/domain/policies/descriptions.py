"""Эффективное описание: своё описание побеждает комментарий источника, комментарий не копируется."""

from __future__ import annotations

from ..entities import Dataset, DatasetField
from ..types import DescriptionProvenance


def normalize_description(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


def effective_field_description(field: DatasetField) -> tuple[str | None, DescriptionProvenance]:
    if field.description:
        return field.description, DescriptionProvenance.DECLARED
    if field.source_comment:
        return field.source_comment, DescriptionProvenance.SOURCE
    return None, DescriptionProvenance.NONE


def effective_dataset_description(dataset: Dataset) -> tuple[str | None, DescriptionProvenance]:
    if dataset.description:
        return dataset.description, DescriptionProvenance.DECLARED
    return None, DescriptionProvenance.NONE
