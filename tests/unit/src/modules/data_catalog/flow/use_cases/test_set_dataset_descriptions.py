from datetime import UTC, datetime

import pytest

from src.modules.data_catalog.domain import (
    UNSET,
    CatalogViewer,
    Dataset,
    DatasetField,
    DatasetFieldNotFoundError,
    DatasetNotFoundError,
    FieldDescriptionChange,
    FieldStatus,
    PhysicalLocator,
    ViewerScope,
)
from src.modules.data_catalog.flow import SetDatasetDescriptions

from ..fakes import InMemoryDatasetRepository, InMemoryFieldRepository

NOW = datetime(2026, 10, 7, tzinfo=UTC)
VIEWER = CatalogViewer("u", "org", ViewerScope.OWN)


def _harness():
    datasets = InMemoryDatasetRepository()
    fields = InMemoryFieldRepository()
    dataset = Dataset(
        id="d1",
        organization_id="org",
        locator=PhysicalLocator("postgresql", "db", 5432, "main", "public", "t"),
        physical_key="k",
        created_at=NOW,
        updated_at=NOW,
        description="old",
    )
    datasets.items["d1"] = dataset
    for name in ("a", "b"):
        fields.items[f"f-{name}"] = DatasetField(
            id=f"f-{name}", dataset_id="d1", name=name, status=FieldStatus.OK, first_seen_at=NOW, last_seen_at=NOW
        )
    use_case = SetDatasetDescriptions(datasets=datasets, fields=fields, clock=lambda: NOW)
    return use_case, dataset, fields


@pytest.mark.asyncio
async def test_omitted_description_is_unchanged_and_null_clears():
    use_case, dataset, _ = _harness()

    await use_case.execute(dataset_id="d1", viewer=VIEWER, actor_user_id="u", description=UNSET)
    assert dataset.description == "old"
    assert dataset.description_updated_by is None

    await use_case.execute(dataset_id="d1", viewer=VIEWER, actor_user_id="u", description=None)
    assert dataset.description is None
    assert (dataset.description_updated_by, dataset.description_updated_at) == ("u", NOW)

    await use_case.execute(dataset_id="d1", viewer=VIEWER, actor_user_id="u", description="   ")
    assert dataset.description is None, "пустая строка после strip тоже очищает"


@pytest.mark.asyncio
async def test_field_descriptions_by_name_and_id_with_attribution():
    use_case, _, fields = _harness()

    result = await use_case.execute(
        dataset_id="d1",
        viewer=VIEWER,
        actor_user_id="u",
        fields=[
            FieldDescriptionChange(description=" first ", name="a"),
            FieldDescriptionChange(description=None, field_id="f-b"),
        ],
    )

    assert {field.name: field.description for field in result.fields} == {"a": "first", "b": None}
    assert fields.items["f-a"].description_updated_by == "u"
    assert fields.items["f-a"].description_updated_at == NOW


@pytest.mark.asyncio
async def test_unknown_field_aborts_whole_request_before_writing():
    use_case, dataset, fields = _harness()

    with pytest.raises(DatasetFieldNotFoundError):
        await use_case.execute(
            dataset_id="d1",
            viewer=VIEWER,
            actor_user_id="u",
            description="new",
            fields=[
                FieldDescriptionChange(description="x", name="a"),
                FieldDescriptionChange(description="y", name="missing"),
            ],
        )

    assert fields.items["f-a"].description is None
    assert dataset.description == "old"


@pytest.mark.asyncio
async def test_invisible_dataset_is_not_found():
    use_case, _, _ = _harness()
    with pytest.raises(DatasetNotFoundError):
        await use_case.execute(dataset_id="nope", viewer=VIEWER, actor_user_id="u", description="x")
