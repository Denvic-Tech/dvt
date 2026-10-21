from datetime import UTC, datetime

import pytest

from src.modules.data_catalog.domain import (
    CatalogViewer,
    ColumnLineage,
    Dataset,
    DatasetField,
    DatasetFieldNotFoundError,
    DatasetLink,
    DatasetNotFoundError,
    ExplainDirection,
    FieldStatus,
    LineageColumnNotFoundError,
    LineageNodePortNotFoundError,
    LineageOp,
    LineageProvenance,
    LineageRef,
    LinkDirection,
    PortLineage,
    PortStatus,
    ProjectLineage,
    ResolvedVia,
    ViewerScope,
    db_table_locator,
)
from src.modules.data_catalog.flow import ExplainField, GetFieldDependents, GetNodeFields

from ..fakes import (
    FakeFreshness,
    FakeRenderer,
    InMemoryDatasetRepository,
    InMemoryFieldRepository,
    InMemoryLinkRepository,
    InMemoryProjectionRepository,
)

NOW = datetime(2026, 10, 20, tzinfo=UTC)
VIEWER = CatalogViewer("u", "org", ViewerScope.OWN)
SOURCE_REF = LineageRef.dataset_field("d1", "f-id")


def _lineage() -> ProjectLineage:
    read_id = ColumnLineage("id", LineageOp.SOURCE, (SOURCE_REF,), details={"template": "lineage.source.table", "field": "id"}, origin=SOURCE_REF)
    renamed = ColumnLineage(
        "customer_id", LineageOp.RENAME, (LineageRef.node_column("r", "output", "id"),),
        details={"template": "lineage.rename", "source": "id"}, origin=SOURCE_REF,
    )
    score = ColumnLineage(
        "score", LineageOp.COMPUTE, (LineageRef.node_column("rn", "output", "customer_id"),),
        details={"template": "lineage.compute.expression", "expression": "customer_id * 2"},
        origin=LineageRef.node_column("e", "output", "score"),
    )
    passed = ColumnLineage(
        "customer_id", LineageOp.PASS, (LineageRef.node_column("rn", "output", "customer_id"),),
        details={"template": "lineage.pass"}, origin=SOURCE_REF,
    )
    return ProjectLineage(
        ports=(
            PortLineage("r", "ReadTableFromDBV3", "output", PortStatus.RESOLVED, (read_id,)),
            PortLineage("rn", "DataFrameRenameColumns", "output", PortStatus.RESOLVED, (renamed,)),
            PortLineage("e", "DataFrameAddColumnByExpression", "output", PortStatus.RESOLVED, (passed, score)),
        )
    )


def _repos(*, with_lineage: bool = True):
    projections = InMemoryProjectionRepository()
    if with_lineage:
        projections.lineage = {"p1": _lineage()}
    fields = InMemoryFieldRepository()
    fields.items["f-id"] = DatasetField(id="f-id", dataset_id="d1", name="id", status=FieldStatus.OK, first_seen_at=NOW, last_seen_at=NOW, description="Customer id")
    datasets = InMemoryDatasetRepository()
    datasets.items["d1"] = Dataset(id="d1", organization_id="org", locator=db_table_locator("postgresql", "db", 5432, "main", "public", "customers"), physical_key="k", created_at=NOW, updated_at=NOW)
    links = InMemoryLinkRepository()
    links.by_project["p1"] = [DatasetLink("l", "d1", "p1", "org", "r", "ReadTableFromDBV3", LinkDirection.READ, ResolvedVia.CONST, 1, NOW, NOW)]
    return projections, fields, datasets, links


@pytest.mark.asyncio
async def test_get_node_fields_resolves_descriptions_and_renders_explanations():
    projections, fields, _, _ = _repos()
    freshness = FakeFreshness()
    use_case = GetNodeFields(projections=projections, fields=fields, renderer=FakeRenderer(), freshness=freshness)

    result = await use_case.execute(project_id="p1", organization_id="org", node_id="e", locale="ru")

    assert freshness.calls == [(("p1",), "org")]
    assert result.port == "output" and result.available_ports == ("output",)
    by_name = {view.name: view for view in result.fields}
    assert by_name["customer_id"].provenance is LineageProvenance.INHERITED
    assert by_name["customer_id"].description == "Customer id"
    assert by_name["customer_id"].description_source == SOURCE_REF
    assert by_name["customer_id"].explanation == "ru:lineage.pass"
    assert by_name["score"].provenance is LineageProvenance.DERIVED and by_name["score"].description is None
    assert by_name["score"].origin.key == "node:e:output:score"


@pytest.mark.asyncio
async def test_get_node_fields_rejects_unknown_node_or_missing_lineage():
    projections, fields, _, _ = _repos()
    use_case = GetNodeFields(projections=projections, fields=fields, renderer=FakeRenderer())
    with pytest.raises(LineageNodePortNotFoundError):
        await use_case.execute(project_id="p1", organization_id="org", node_id="ghost")
    with pytest.raises(LineageNodePortNotFoundError):
        await use_case.execute(project_id="p1", organization_id="org", node_id="e", port="nope")

    empty, fields, _, _ = _repos(with_lineage=False)
    with pytest.raises(LineageNodePortNotFoundError):
        await GetNodeFields(projections=empty, fields=fields, renderer=FakeRenderer()).execute(project_id="p1", organization_id="org", node_id="e")


@pytest.mark.asyncio
async def test_explain_field_walks_upstream_to_the_source_field():
    projections, fields, _, _ = _repos()
    use_case = ExplainField(projections=projections, fields=fields, renderer=FakeRenderer())

    explanation = await use_case.execute(project_id="p1", organization_id="org", node_id="e", column="score", locale="en")

    assert [step.ref.key for step in explanation.steps] == [
        "node:e:output:score",
        "node:rn:output:customer_id",
        "node:r:output:id",
        "ds:d1:f-id",
    ]
    assert explanation.steps[0].text == "en:lineage.compute.expression"
    assert explanation.steps[-1].field_name == "id"
    assert explanation.description.provenance is LineageProvenance.DERIVED

    downstream = await use_case.execute(
        project_id="p1", organization_id="org", node_id="r", column="id", direction=ExplainDirection.DOWNSTREAM, max_depth=1
    )
    assert [step.ref.key for step in downstream.steps] == ["node:r:output:id", "node:rn:output:customer_id"]
    assert downstream.truncated is True

    with pytest.raises(LineageColumnNotFoundError):
        await use_case.execute(project_id="p1", organization_id="org", node_id="e", column="nope")


@pytest.mark.asyncio
async def test_get_field_dependents_spans_consumer_projects_and_validates_field():
    projections, fields, datasets, links = _repos()
    freshness = FakeFreshness()
    use_case = GetFieldDependents(datasets=datasets, fields=fields, links=links, projections=projections, freshness=freshness)

    items = await use_case.execute(dataset_id="d1", field_id="f-id", viewer=VIEWER)

    assert freshness.calls == [(("p1",), "org")]
    assert [(item.node_id, item.column, item.depth) for item in items] == [
        ("r", "id", 1),
        ("rn", "customer_id", 2),
        ("e", "customer_id", 3),
        ("e", "score", 3),
    ]

    with pytest.raises(DatasetFieldNotFoundError):
        await use_case.execute(dataset_id="d1", field_id="ghost", viewer=VIEWER)
    with pytest.raises(DatasetNotFoundError):
        await use_case.execute(dataset_id="nope", field_id="f-id", viewer=VIEWER)
