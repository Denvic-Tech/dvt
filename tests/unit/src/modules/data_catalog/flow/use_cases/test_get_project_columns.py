from datetime import UTC, datetime

import pytest

from src.modules.data_catalog.domain import (
    ColumnLineage,
    Dataset,
    DatasetField,
    FieldStatus,
    LineageOp,
    LineageProvenance,
    LineageRef,
    NodeColumnAnnotation,
    PortLineage,
    PortStatus,
    ProjectLineage,
    db_table_locator,
)
from src.modules.data_catalog.flow import GetProjectColumns

from ..fakes import (
    FakeFreshness,
    InMemoryAnnotationRepository,
    InMemoryDatasetRepository,
    InMemoryFieldRepository,
    InMemoryProjectionRepository,
)

NOW = datetime(2026, 10, 23, tzinfo=UTC)
SOURCE_REF = LineageRef.dataset_field("d1", "f-id")


def _lineage() -> ProjectLineage:
    read_id = ColumnLineage("id", LineageOp.SOURCE, (SOURCE_REF,), origin=SOURCE_REF)
    renamed = ColumnLineage("customer_id", LineageOp.RENAME, (LineageRef.node_column("r", "output", "id"),), origin=SOURCE_REF)
    passed = ColumnLineage("customer_id", LineageOp.PASS, (LineageRef.node_column("rn", "output", "customer_id"),), origin=SOURCE_REF)
    score = ColumnLineage(
        "score", LineageOp.COMPUTE, (LineageRef.node_column("rn", "output", "customer_id"),),
        origin=LineageRef.node_column("e", "output", "score"),
    )
    return ProjectLineage(
        ports=(
            PortLineage("r", "ReadTableFromDBV3", "output", PortStatus.RESOLVED, (read_id,)),
            PortLineage("rn", "DataFrameRenameColumns", "output", PortStatus.RESOLVED, (renamed,)),
            PortLineage("e", "DataFrameAddColumnByExpression", "output", PortStatus.RESOLVED, (passed, score)),
            PortLineage("w", "WriteDataFrameToDBV4", "df", PortStatus.UNRESOLVED, (), role="input"),
        ),
        truncated=True,
    )


def _use_case(*, with_lineage: bool = True):
    projections = InMemoryProjectionRepository()
    if with_lineage:
        projections.lineage = {"p1": _lineage()}
    fields = InMemoryFieldRepository()
    fields.items["f-id"] = DatasetField(id="f-id", dataset_id="d1", name="id", status=FieldStatus.OK, first_seen_at=NOW, last_seen_at=NOW, description="Customer id")
    datasets = InMemoryDatasetRepository()
    datasets.items["d1"] = Dataset(
        id="d1", organization_id="org", locator=db_table_locator("postgresql", "db", 5432, "main", "public", "customers"),
        physical_key="k", created_at=NOW, updated_at=NOW, location="main.public.customers @ db:5432",
    )
    annotations = InMemoryAnnotationRepository()
    annotations.items["a1"] = NodeColumnAnnotation(
        id="a1", project_id="p1", node_id="rn", port="output", column="customer_id", description="Клиент",
        created_at=NOW, updated_at=NOW, description_updated_by="u1",
    )
    annotations.items["a2"] = NodeColumnAnnotation(
        id="a2", project_id="p1", node_id="e", port="output", column="old_score", description="Сирота",
        created_at=NOW, updated_at=NOW,
    )
    freshness = FakeFreshness()
    use_case = GetProjectColumns(projections=projections, fields=fields, datasets=datasets, annotations=annotations, freshness=freshness)
    return use_case, freshness


@pytest.mark.asyncio
async def test_project_columns_group_by_origin_with_overrides_orphans_and_unresolved_ports():
    use_case, freshness = _use_case()

    result = await use_case.execute(project_id="p1", organization_id="org")

    assert freshness.calls == [(("p1",), "org")]
    assert result.lineage_available is True and result.truncated is True
    assert [group.origin.key for group in result.groups] == ["ds:d1:f-id", "node:e:output:score"]

    customer = result.groups[0]
    assert (customer.dataset_location, customer.field_name, customer.description.text) == (
        "main.public.customers @ db:5432", "id", "Customer id",
    )
    assert [(item.node_id, item.depth, item.description.text, item.is_override) for item in customer.occurrences] == [
        ("r", 1, "Customer id", False),
        ("rn", 2, "Клиент", True),
        ("e", 3, "Клиент", False),
    ]
    assert customer.override_count == 1
    assert customer.occurrences[2].description.provenance is LineageProvenance.INHERITED
    assert customer.occurrences[2].description.source == LineageRef.node_column("rn", "output", "customer_id")

    assert [(port.node_id, port.port, port.role) for port in result.unresolved_ports] == [("w", "df", "input")]

    rows = {(row.name, row.start.node_id): row for row in result.rows}
    assert set(rows) == {("id", "r"), ("customer_id", "rn"), ("score", "e")}
    assert rows[("customer_id", "rn")].is_rename and rows[("customer_id", "rn")].renamed_from == "id"
    assert [item.node_id for item in rows[("customer_id", "rn")].occurrences] == ["rn", "e"]
    assert rows[("customer_id", "rn")].description.text == "Клиент"
    assert [target.scope for target in rows[("id", "r")].targets] == ["project", "global"]
    assert rows[("score", "e")].depends_on == (rows[("customer_id", "rn")].id,)
    assert [item.column for item in result.orphaned_annotations] == ["old_score"]


@pytest.mark.asyncio
async def test_project_without_lineage_returns_an_empty_catalog_instead_of_an_error():
    use_case, _ = _use_case(with_lineage=False)

    result = await use_case.execute(project_id="p1", organization_id="org")

    assert result.lineage_available is False
    assert result.groups == () and result.orphaned_annotations == ()
