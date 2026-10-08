from datetime import UTC, datetime

import pytest

from src.modules.data_catalog.domain import (
    LINEAGE_SCHEMA_VERSION,
    ConnectionLocator,
    DiagnosticReason,
    GraphEdge,
    GraphInputValue,
    GraphNode,
    LinkDirection,
    ProjectCatalogProjection,
    ProjectGraphSnapshot,
    ProjectionStamp,
    ProjectionStatus,
    ProjectStampSource,
    ResolvedVia,
    SqlTableRef,
)
from src.modules.data_catalog.domain.policies import variables_fingerprint
from src.modules.data_catalog.flow import (
    ProjectionRebuildFailedError,
    RebuildProjectCatalogProjection,
)

from ..fakes import (
    FakeConnectionLocatorGateway,
    FakeExpressionResolver,
    FakeGraphGateway,
    FakeSqlExtractor,
    InMemoryConnectionRepository,
    InMemoryDatasetRepository,
    InMemoryLinkRepository,
    InMemoryProjectionRepository,
)

PG = ConnectionLocator(id="conn-1", dialect="postgres", host="db", port=5432, database="main", revision="r1")
CONNECTION_NODE = GraphNode(
    ui_id="conn", name="GetExistDBConnection", inputs={"connection_id": GraphInputValue.const("conn-1")}
)


def _edge(target: str) -> GraphEdge:
    return GraphEdge(source="conn", target=target, source_handle="output-connection", target_handle="input-connection")


def _snapshot(*nodes: GraphNode, revision: int = 3, variables=None) -> ProjectGraphSnapshot:
    return ProjectGraphSnapshot(
        stamp_source=ProjectStampSource("p1", "org", revision, variables),
        nodes=(CONNECTION_NODE, *nodes),
        edges=tuple(_edge(node.ui_id) for node in nodes),
    )


class Harness:
    def __init__(self, snapshot, *, locators=None, expressions=None, sql_tables=(), sql_fail=None):
        self.datasets = InMemoryDatasetRepository()
        self.connections = InMemoryConnectionRepository()
        self.links = InMemoryLinkRepository()
        self.projections = InMemoryProjectionRepository()
        self.graph = FakeGraphGateway(snapshot)
        self.use_case = RebuildProjectCatalogProjection(
            datasets=self.datasets,
            connections=self.connections,
            links=self.links,
            projections=self.projections,
            graph_gateway=self.graph,
            connection_locator=FakeConnectionLocatorGateway(locators if locators is not None else {"conn-1": PG}),
            expression_resolver=FakeExpressionResolver(expressions),
            sql_extractor=FakeSqlExtractor(sql_tables, fail=sql_fail),
            clock=lambda: datetime(2026, 10, 7, tzinfo=UTC),
        )

    async def run(self, **kwargs):
        return await self.use_case.execute(project_id="p1", organization_id="org", **kwargs)


@pytest.mark.asyncio
async def test_rebuild_registers_datasets_links_and_connections():
    reader = GraphNode("r", "ReadTableFromDBV3", {"table_name": GraphInputValue.const("public.customers")})
    writer = GraphNode("w", "WriteDataFrameToDBV4", {"table_name": GraphInputValue.const("customers")})
    harness = Harness(_snapshot(reader, writer))

    result = await harness.run()

    assert result.status == "ok"
    assert result.link_count == 2
    assert len(harness.datasets.items) == 1, "один physical_key -> одна сущность"
    dataset = next(iter(harness.datasets.items.values()))
    assert dataset.physical_key == "postgresql://db:5432/main/public/customers"
    links = harness.links.by_project["p1"]
    assert {(link.node_id, link.direction, link.resolved_via) for link in links} == {
        ("r", LinkDirection.READ, ResolvedVia.CONST),
        ("w", LinkDirection.WRITE, ResolvedVia.CONST),
    }
    assert harness.connections.touched[0][:2] == (dataset.id, "conn-1")
    projection = harness.projections.items["p1"]
    assert projection.status is ProjectionStatus.OK
    assert projection.stamp.graph_revision == 3
    assert projection.depends_on_project_variables is False


@pytest.mark.asyncio
async def test_rebuild_is_skipped_when_stamp_is_current_and_forced_when_requested():
    harness = Harness(_snapshot(GraphNode("r", "ReadTableFromDBV3", {"table_name": GraphInputValue.const("t")})))
    assert (await harness.run()).status == "ok"
    assert (await harness.run()).status == "skipped"
    assert (await harness.run(force=True)).status == "ok"
    assert harness.graph.locks == 3


@pytest.mark.asyncio
async def test_expression_locators_mark_variable_dependency_and_unresolved_ones_are_diagnosed():
    resolved = GraphNode(
        "w", "WriteDataFrameToDBV4", {"table_name": GraphInputValue.expr("{{ project_variables.t }}", "template")}
    )
    unresolved = GraphNode(
        "u", "ReadTableFromDBV3", {"table_name": GraphInputValue.expr("{{ input_variables.x }}", "template")}
    )
    harness = Harness(
        _snapshot(resolved, unresolved, variables={"t": "orders"}),
        expressions={"{{ project_variables.t }}": "orders"},
    )

    result = await harness.run()

    projection = result.projection
    assert projection.depends_on_project_variables is True
    assert projection.stamp.variables_fingerprint == variables_fingerprint({"t": "orders"})
    assert [link.resolved_via for link in harness.links.by_project["p1"]] == [ResolvedVia.EXPRESSION]
    assert [(d.node_id, d.reason) for d in projection.diagnostics] == [("u", DiagnosticReason.EXPRESSION_UNRESOLVED)]


@pytest.mark.asyncio
async def test_sql_nodes_register_each_referenced_table_as_read():
    sql_node = GraphNode("q", "ReadQueryFromDBV3", {"sql_code": GraphInputValue.const("select ...")})
    harness = Harness(
        _snapshot(sql_node),
        sql_tables=[SqlTableRef(table="a", schema="s1"), SqlTableRef(table="b")],
    )

    result = await harness.run()

    assert result.link_count == 2
    keys = sorted(item.physical_key for item in harness.datasets.items.values())
    assert keys == ["postgresql://db:5432/main/public/b", "postgresql://db:5432/main/s1/a"]
    assert all(link.resolved_via is ResolvedVia.SQL for link in harness.links.by_project["p1"])


@pytest.mark.asyncio
async def test_sql_parse_failure_and_missing_connection_become_diagnostics():
    sql_node = GraphNode("q", "ExecuteSQL", {"sql_code": GraphInputValue.const("broken")})
    harness = Harness(_snapshot(sql_node), sql_fail="parse: boom")
    result = await harness.run()
    assert [(d.node_id, d.reason) for d in result.projection.diagnostics] == [("q", DiagnosticReason.SQL_PARSE_FAILED)]
    assert harness.links.by_project["p1"] == []

    missing = Harness(
        _snapshot(GraphNode("r", "ReadTableFromDBV3", {"table_name": GraphInputValue.const("t")})),
        locators={},
    )
    result = await missing.run()
    assert [(d.node_id, d.reason) for d in result.projection.diagnostics] == [("r", DiagnosticReason.CONNECTION_MISSING)]


@pytest.mark.asyncio
async def test_failure_keeps_previous_stamp_and_does_not_raise_unless_asked():
    harness = Harness(_snapshot(GraphNode("r", "ReadTableFromDBV3", {"table_name": GraphInputValue.const("t")})))
    harness.projections.items["p1"] = ProjectCatalogProjection(
        project_id="p1",
        organization_id="org",
        stamp=ProjectionStamp(2, "old", LINEAGE_SCHEMA_VERSION),
        built_at=datetime(2026, 1, 1, tzinfo=UTC),
        status=ProjectionStatus.OK,
    )

    async def boom(project_id, links):
        raise RuntimeError("db down")

    harness.links.replace_for_project = boom  # type: ignore[method-assign]

    result = await harness.run()

    assert result.status == "failed"
    stored = harness.projections.items["p1"]
    assert stored.status is ProjectionStatus.FAILED
    assert stored.stamp.graph_revision == 2, "старый штамп сохранён, чтобы следующее сохранение повторило попытку"
    assert "db down" in (stored.error or "")

    with pytest.raises(ProjectionRebuildFailedError):
        await harness.run(raise_on_error=True)


@pytest.mark.asyncio
async def test_missing_project_is_skipped():
    harness = Harness(None)
    assert (await harness.run()).status == "skipped"
