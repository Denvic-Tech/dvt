from datetime import UTC, datetime

import pytest

from src.modules.data_catalog.domain import (
    Dataset,
    DatasetField,
    DatasetFieldNotFoundError,
    DescriptionProvenance,
    FieldRef,
    FieldStatus,
    InvalidFieldReferenceError,
    PhysicalLocator,
)
from src.modules.data_catalog.domain.policies import (
    effective_dataset_description,
    effective_field_description,
    normalize_description,
    resolve_field,
)

NOW = datetime(2026, 10, 7, tzinfo=UTC)


def _field(**overrides) -> DatasetField:
    values = {
        "id": "f1", "dataset_id": "d", "name": "col", "status": FieldStatus.OK, "first_seen_at": NOW, "last_seen_at": NOW
    }
    values.update(overrides)
    return DatasetField(**values)


def test_field_description_provenance_matrix():
    assert effective_field_description(_field(description="mine", source_comment="db")) == (
        "mine",
        DescriptionProvenance.DECLARED,
    )
    assert effective_field_description(_field(source_comment="db")) == ("db", DescriptionProvenance.SOURCE)
    assert effective_field_description(_field()) == (None, DescriptionProvenance.NONE)


def test_dataset_description_is_never_sourced_from_comments():
    dataset = Dataset(
        id="d",
        organization_id="o",
        locator=PhysicalLocator("postgresql", "h", 5432, "db", "public", "t"),
        physical_key="k",
        created_at=NOW,
        updated_at=NOW,
    )
    assert effective_dataset_description(dataset) == (None, DescriptionProvenance.NONE)
    dataset.description = "table"
    assert effective_dataset_description(dataset) == ("table", DescriptionProvenance.DECLARED)


@pytest.mark.parametrize("raw,expected", [(None, None), ("  ", None), ("  text ", "text")])
def test_normalize_description(raw, expected):
    assert normalize_description(raw) == expected


def test_field_ref_requires_exactly_one_identifier():
    with pytest.raises(InvalidFieldReferenceError):
        FieldRef()
    with pytest.raises(InvalidFieldReferenceError):
        FieldRef(field_id="a", name="b")
    assert FieldRef(name="  col ").name == "col"


def test_resolve_field_by_id_and_name():
    fields = [_field(id="f1", name="a"), _field(id="f2", name="b")]
    assert resolve_field(fields, FieldRef(field_id="f2")).name == "b"
    assert resolve_field(fields, FieldRef(name="a")).id == "f1"
    with pytest.raises(DatasetFieldNotFoundError):
        resolve_field(fields, FieldRef(name="zzz"))
