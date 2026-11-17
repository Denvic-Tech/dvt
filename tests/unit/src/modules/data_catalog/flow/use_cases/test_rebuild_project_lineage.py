from datetime import UTC, datetime

import pytest

from src.modules.data_catalog.domain import (
    DatasetField,
    DiagnosticReason,
    FieldStatus,
    GraphEdge,
    GraphInputValue,
    GraphNode,
    LineageOp,
    NodePortTypes,
    ObservedField,
    ObservedPortSchema,
    PortStatus,
    ProjectGraphSnapshot,
    ProjectStampSource,
    ResolvedVia,
    SourceSeedContext,
    SqlColumnKind,
    SqlColumnLineage,
    SqlLineageResult,
    SqlSourceColumn,
)
from src.modules.data_catalog.domain.policies import build_builtin_rules
from src.modules.data_catalog.flow import RebuildProjectLineage

from ..fakes import (
    FakePortTypeGateway,
    FakeSqlLineageExtractor,
    InMemoryFieldRepository,
    InMemoryPortObservationRepository,
)

NOW = datetime(2026, 10, 20, tzinfo=UTC)
TYPES = {
    "ReadTableFromDBV3": NodePortTypes(dataframe_outputs=("output",)),
    "ReadQueryFromDBV3": NodePortTypes(dataframe_outputs=("output",)),
    "DataFrameJoin": NodePortTypes(dataframe_inputs=frozenset({"left", "right"}), dataframe_outputs=("output",), defaults={"how": "left"}),
}


def _field(dataset_id: str, name: str) -> DatasetField:
    return DatasetField(id=f"{dataset_id}-{name}", dataset_id=dataset_id, name=name, status=FieldStatus.OK, first_seen_at=NOW, last_seen_at=NOW)


def _snapshot() -> ProjectGraphSnapshot:
    return ProjectGraphSnapshot(
        stamp_source=ProjectStampSource("p1", "org", 1),
        nodes=(
            GraphNode("r", "ReadTableFromDBV3", {"table_name": GraphInputValue.const("customers")}),
            GraphNode("q", "ReadQueryFromDBV3", {"sql_code": GraphInputValue.const("select ...")}),
            GraphNode("j", "DataFrameJoin", {"left_on": GraphInputValue.const(["id"]), "right_on": GraphInputValue.const(["cust"])}),
        ),
        edges=(
            GraphEdge("r", "j", "output-output", "input-left"),
            GraphEdge("q", "j", "output-output", "input-right"),
        ),
    )


@pytest.mark.asyncio
async def test_observed_port_schemas_fill_dynamic_nodes():
    fields = InMemoryFieldRepository()
    fields.items["d-cust-id"] = _field("d-cust", "id")
    types = {
        "ReadTableFromDBV3": NodePortTypes(dataframe_outputs=("output",)),
        "DataFrameExecCode": NodePortTypes(dataframe_inputs=frozenset({"df"}), dataframe_outputs=("output",)),
    }
    snapshot = ProjectGraphSnapshot(
        stamp_source=ProjectStampSource("p1", "org", 3),
        nodes=(
            GraphNode("r", "ReadTableFromDBV3", {"table_name": GraphInputValue.const("customers")}),
            GraphNode("x", "DataFrameExecCode", {"code": GraphInputValue.const("df['score'] = 1")}),
        ),
        edges=(GraphEdge("r", "x", "output-output", "input-df"),),
    )
    observations = InMemoryPortObservationRepository()
    observations.items[("p1", "x", "output")] = ObservedPortSchema(
        "p1", "x", "output", (ObservedField("id", "INT", False, 1), ObservedField("score", "INT", True, 2)), NOW, graph_revision=3
    )
    use_case = RebuildProjectLineage(
        fields=fields, port_types=FakePortTypeGateway(types), rules=build_builtin_rules(), observations=observations
    )
    seeds = [SourceSeedContext(node_id="r", node_name="ReadTableFromDBV3", dataset_ids=("d-cust",), resolved_via=ResolvedVia.CONST)]

    result = await use_case.execute(snapshot=snapshot, project_variables={}, seeds=seeds)

    port = next(item for item in result.lineage.ports if item.node_id == "x")
    assert (port.status, port.reason) == (PortStatus.PARTIALLY_RESOLVED, DiagnosticReason.LINEAGE_SCHEMA_OBSERVED)
    assert [(column.name, column.op, column.deps_unknown) for column in port.columns] == [
        ("id", LineageOp.PASS, False),
        ("score", LineageOp.UNKNOWN, True),
    ]
    assert port.columns[0].origin.key == "ds:d-cust:d-cust-id", "same-named input column passes through"
    assert port.columns[1].origin.key == "node:x:output:score"


@pytest.mark.asyncio
async def test_table_and_sql_seeds_feed_the_derivation():
    fields = InMemoryFieldRepository()
    for item in (_field("d-cust", "id"), _field("d-cust", "name"), _field("d-ord", "cust"), _field("d-ord", "amount")):
        fields.items[item.id] = item
    sql_result = SqlLineageResult(
        columns=(
            SqlColumnLineage("cust", SqlColumnKind.COLUMN, (SqlSourceColumn("orders", "cust"),)),
            SqlColumnLineage("total", SqlColumnKind.AGGREGATE, (SqlSourceColumn("orders", "amount"),), expression="SUM(amount)"),
        )
    )
    extractor = FakeSqlLineageExtractor(sql_result)
    use_case = RebuildProjectLineage(fields=fields, port_types=FakePortTypeGateway(TYPES), rules=build_builtin_rules(), sql_lineage=extractor)

    result = await use_case.execute(
        snapshot=_snapshot(),
        project_variables={},
        seeds=[
            SourceSeedContext(node_id="r", node_name="ReadTableFromDBV3", dataset_ids=("d-cust",), resolved_via=ResolvedVia.CONST, column_filter=("id",)),
            SourceSeedContext(node_id="q", node_name="ReadQueryFromDBV3", dataset_ids=("d-ord",), resolved_via=ResolvedVia.SQL, references={"orders": "d-ord"}, sql="select ...", dialect="postgresql"),
        ],
    )

    assert result.diagnostics == ()
    assert extractor.schema.tables == {"orders": ("cust", "amount")}
    ports = {port.node_id: {c.name: c for c in port.columns} for port in result.lineage.ports}
    assert set(ports["r"]) == {"id"}, "column filter narrows the table seed"
    assert ports["q"]["total"].op is LineageOp.AGGREGATE
    assert set(ports["j"]) == {"id", "cust", "total"}
    assert ports["j"]["total"].origin.key == "node:q:output:total"
    assert ports["j"]["id"].origin.key == "ds:d-cust:d-cust-id"


@pytest.mark.asyncio
async def test_unsynced_table_and_missing_sql_extractor_are_diagnosed():
    use_case = RebuildProjectLineage(fields=InMemoryFieldRepository(), port_types=FakePortTypeGateway(TYPES), rules=build_builtin_rules())

    result = await use_case.execute(
        snapshot=_snapshot(),
        project_variables={},
        seeds=[
            SourceSeedContext(node_id="r", node_name="ReadTableFromDBV3", dataset_ids=("d-cust",), resolved_via=ResolvedVia.CONST),
            SourceSeedContext(node_id="q", node_name="ReadQueryFromDBV3", dataset_ids=("d-ord",), resolved_via=ResolvedVia.SQL, sql="select 1", dialect="postgresql"),
        ],
    )

    ports = {port.node_id: port for port in result.lineage.ports}
    assert ports["r"].status is PortStatus.UNRESOLVED and ports["r"].reason is DiagnosticReason.LINEAGE_SCHEMA_NOT_SYNCED
    assert ports["q"].reason is DiagnosticReason.LINEAGE_SQL_UNSUPPORTED
    assert ports["j"].status is PortStatus.UNRESOLVED
    assert [d.reason for d in result.diagnostics] == [DiagnosticReason.LINEAGE_SCHEMA_NOT_SYNCED]
