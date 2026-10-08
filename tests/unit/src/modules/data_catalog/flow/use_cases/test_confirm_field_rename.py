from datetime import UTC, datetime

import pytest

from src.modules.data_catalog.domain import (
    CatalogViewer,
    Dataset,
    DatasetField,
    DatasetFieldNotFoundError,
    FieldRef,
    FieldRenameNotApplicableError,
    FieldStatus,
    PhysicalLocator,
    ViewerScope,
)
from src.modules.data_catalog.flow import ConfirmFieldRename

from ..fakes import InMemoryDatasetRepository, InMemoryFieldRepository

EARLIER = datetime(2026, 10, 1, tzinfo=UTC)
NOW = datetime(2026, 10, 7, tzinfo=UTC)
VIEWER = CatalogViewer("u", "org", ViewerScope.OWN)


def _harness(old_status=FieldStatus.MISSING, new_status=FieldStatus.NEW):
    datasets = InMemoryDatasetRepository()
    datasets.items["d1"] = Dataset(
        id="d1",
        organization_id="org",
        locator=PhysicalLocator("postgresql", "db", 5432, "main", "public", "t"),
        physical_key="k",
        created_at=EARLIER,
        updated_at=EARLIER,
    )
    fields = InMemoryFieldRepository()
    fields.items["f-old"] = DatasetField(
        id="f-old",
        dataset_id="d1",
        name="customer_nm",
        status=old_status,
        first_seen_at=EARLIER,
        last_seen_at=EARLIER,
        dtype="STRING",
        description="Имя клиента",
        description_updated_by="u-old",
        observed_via=("conn-a",),
    )
    fields.items["f-new"] = DatasetField(
        id="f-new",
        dataset_id="d1",
        name="customer_name",
        status=new_status,
        first_seen_at=NOW,
        last_seen_at=NOW,
        dtype="STRING",
        ordinal=3,
        source_comment="renamed",
        observed_via=("conn-b",),
    )
    return ConfirmFieldRename(datasets=datasets, fields=fields, clock=lambda: NOW), fields


@pytest.mark.asyncio
async def test_rename_moves_identity_onto_old_row_and_deletes_new_one():
    use_case, fields = _harness()

    result = await use_case.execute(
        dataset_id="d1", viewer=VIEWER, missing=FieldRef(name="customer_nm"), new=FieldRef(field_id="f-new")
    )

    assert result.id == "f-old"
    assert (result.name, result.status, result.ordinal, result.source_comment) == (
        "customer_name",
        FieldStatus.OK,
        3,
        "renamed",
    )
    assert result.description == "Имя клиента", "описание старого поля сохраняется"
    assert result.observed_via == ("conn-a", "conn-b")
    assert set(fields.items) == {"f-old"}
    assert fields.deleted == ["f-new"]


@pytest.mark.asyncio
async def test_rename_preconditions():
    use_case, _ = _harness(old_status=FieldStatus.OK)
    with pytest.raises(FieldRenameNotApplicableError):
        await use_case.execute(dataset_id="d1", viewer=VIEWER, missing=FieldRef(field_id="f-old"), new=FieldRef(field_id="f-new"))

    use_case, _ = _harness(new_status=FieldStatus.MISSING)
    with pytest.raises(FieldRenameNotApplicableError):
        await use_case.execute(dataset_id="d1", viewer=VIEWER, missing=FieldRef(field_id="f-old"), new=FieldRef(field_id="f-new"))

    use_case, _ = _harness()
    with pytest.raises(FieldRenameNotApplicableError):
        await use_case.execute(dataset_id="d1", viewer=VIEWER, missing=FieldRef(field_id="f-old"), new=FieldRef(field_id="f-old"))

    with pytest.raises(DatasetFieldNotFoundError):
        await use_case.execute(dataset_id="d1", viewer=VIEWER, missing=FieldRef(name="ghost"), new=FieldRef(field_id="f-new"))
