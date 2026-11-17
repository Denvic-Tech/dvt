from datetime import UTC, datetime

import pytest

from src.modules.data_catalog.domain import (
    Dataset,
    DatasetField,
    DatasetLink,
    FieldStatus,
    LinkDirection,
    ObservedField,
    ObservedNodeSchema,
    ResolvedVia,
    db_table_locator,
    default_registry,
)
from src.modules.data_catalog.flow import RecordObservedSchema

from ..fakes import (
    InMemoryConnectionRepository,
    InMemoryDatasetRepository,
    InMemoryFieldRepository,
    InMemoryLinkRepository,
)

EARLIER = datetime(2026, 10, 1, tzinfo=UTC)
NOW = datetime(2026, 10, 7, tzinfo=UTC)


def _harness():
    datasets = InMemoryDatasetRepository()
    datasets.items["d1"] = Dataset(
        id="d1",
        organization_id="org",
        locator=db_table_locator("postgresql", "db", 5432, "main", "public", "Orders"),
        physical_key="k",
        created_at=EARLIER,
        updated_at=EARLIER,
    )
    fields = InMemoryFieldRepository()
    fields.items["f-id"] = DatasetField(
        id="f-id", dataset_id="d1", name="id", status=FieldStatus.OK, first_seen_at=EARLIER, last_seen_at=EARLIER, dtype="INT"
    )
    fields.items["f-old"] = DatasetField(
        id="f-old", dataset_id="d1", name="old", status=FieldStatus.OK, first_seen_at=EARLIER, last_seen_at=EARLIER
    )
    links = InMemoryLinkRepository()
    links.by_project["p1"] = [
        DatasetLink("l", "d1", "p1", "org", "node-1", "ReadTableFromDBV3", LinkDirection.READ, ResolvedVia.CONST, 1, EARLIER, EARLIER)
    ]
    connections = InMemoryConnectionRepository()
    use_case = RecordObservedSchema(
        datasets=datasets, fields=fields, connections=connections, links=links, sources=default_registry()
    )
    return use_case, datasets, fields, connections


def _observation(**overrides) -> ObservedNodeSchema:
    values = {
        "project_id": "p1",
        "node_id": "node-1",
        "connection_id": "conn-1",
        "connection_revision": "rev-2",
        "fields": (ObservedField("id", "FLOAT"), ObservedField("created", "DATETIME", ordinal=2)),
        "observed_at": NOW,
        "trust_types": True,
        "partial": False,
        "locator_parts": {"table": "orders"},
    }
    values.update(overrides)
    return ObservedNodeSchema(**values)


@pytest.mark.asyncio
async def test_trusted_observation_updates_types_marks_missing_and_syncs_dataset():
    use_case, datasets, fields, connections = _harness()

    outcome = await use_case.execute(_observation())

    assert outcome.dataset_ids == ("d1",) and outcome.trusted_types is True
    by_name = {f.name: f for f in fields.items.values()}
    assert (by_name["id"].dtype, by_name["id"].status) == ("FLOAT", FieldStatus.TYPE_CHANGED)
    assert by_name["created"].status is FieldStatus.NEW
    assert by_name["old"].status is FieldStatus.MISSING
    dataset = datasets.items["d1"]
    assert dataset.observed_at_run == NOW and dataset.schema_synced_at == NOW
    assert connections.touched == [("d1", "conn-1", "rev-2")]


@pytest.mark.asyncio
async def test_untrusted_observation_only_tracks_presence():
    use_case, datasets, fields, _ = _harness()

    await use_case.execute(_observation(trust_types=False))

    by_name = {f.name: f for f in fields.items.values()}
    assert (by_name["id"].dtype, by_name["id"].status) == ("INT", FieldStatus.OK)
    assert by_name["created"].dtype is None
    dataset = datasets.items["d1"]
    assert dataset.observed_at_run == NOW
    assert dataset.schema_synced_at is None, "FULL-прогон не считается синхронизацией типов"


@pytest.mark.asyncio
async def test_partial_observation_never_marks_missing():
    use_case, _, fields, _ = _harness()
    await use_case.execute(_observation(partial=True))
    assert fields.items["f-old"].status is FieldStatus.OK


@pytest.mark.asyncio
async def test_unknown_node_and_table_mismatch_are_skipped():
    use_case, datasets, _, _ = _harness()

    assert (await use_case.execute(_observation(node_id="other"))).dataset_ids == ()
    assert (await use_case.execute(_observation(locator_parts={"table": "customers"}))).dataset_ids == ()
    assert datasets.items["d1"].observed_at_run is None
