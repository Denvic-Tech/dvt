from __future__ import annotations

from datetime import UTC, datetime

from src.modules.data_catalog.domain import (
    DiagnosticReason,
    LineageOp,
    LineageProvenance,
    LineageRef,
    NodeColumnAnnotation,
    ObservedField,
    ObservedPortSchema,
    PortColumns,
    PortStatus,
)
from src.modules.data_catalog.domain.policies import (
    DescriptionResolver,
    build_builtin_rules,
    build_column_rows,
    can_use_observation,
    collect_unresolved_ports,
    derive_project_lineage,
    group_columns_by_origin,
    index_lineage,
)

from .helpers import edge, node, port_types, snapshot, source_seed

NOW = datetime(2026, 10, 27, tzinfo=UTC)
RULES = build_builtin_rules()


def _observation(node_id: str, *names: str, port: str = "output") -> ObservedPortSchema:
    return ObservedPortSchema(
        project_id="p1", node_id=node_id, port=port,
        columns=tuple(ObservedField(name, "STRING", True, index) for index, name in enumerate(names, start=1)),
        observed_at=NOW, graph_revision=1, task_id="t1",
    )


def _graph():
    return snapshot(
        node("a", "ReadTableFromDBV3", table_name="deals"),
        node("x", "DataFrameExecCode", code="df['q'] = 1"),
        node("s", "DataFrameSelectColumns", columns=["a", "b"]),
        node("rn", "DataFrameRenameColumns", mapping={"b": "c"}),
        node("w", "WriteDataFrameToDBV4"),
        edges=(edge("a", "x"), edge("x", "s"), edge("s", "rn"), edge("rn", "w")),
    )


def _derive(observed=None):
    lineage, diagnostics = derive_project_lineage(
        _graph(), port_types=port_types, rules=RULES,
        seeds={"a": {"output": source_seed("da", "a", "b")}}, observed=observed,
    )
    return {(port.node_id, port.port): port for port in lineage.ports}, lineage, diagnostics


def test_without_observation_everything_below_exec_code_is_unresolved():
    ports, _, _ = _derive()

    assert ports[("x", "output")].status is PortStatus.UNRESOLVED
    assert ports[("x", "output")].reason is DiagnosticReason.LINEAGE_INPUT_DYNAMIC
    assert all(ports[key].status is PortStatus.UNRESOLVED for key in (("s", "output"), ("rn", "output"), ("w", "df")))


def test_observation_fills_the_dynamic_port_and_unblocks_the_chain():
    ports, lineage, _ = _derive({("x", "output"): _observation("x", "a", "b", "q")})

    exec_port = ports[("x", "output")]
    assert (exec_port.status, exec_port.reason) == (PortStatus.PARTIALLY_RESOLVED, DiagnosticReason.LINEAGE_SCHEMA_OBSERVED)
    assert "arbitrary Python code" in (exec_port.detail or "")
    assert [(column.name, column.op, column.deps, column.deps_unknown) for column in exec_port.columns] == [
        ("a", LineageOp.PASS, (LineageRef.node_column("a", "output", "a"),), False),
        ("b", LineageOp.PASS, (LineageRef.node_column("a", "output", "b"),), False),
        ("q", LineageOp.UNKNOWN, (), True),
    ]
    assert exec_port.columns[0].origin == LineageRef.dataset_field("da", "f-a"), "same-named input column: assumed pass-through"
    assert exec_port.columns[0].details == {"template": "lineage.pass.observed", "node": "DataFrameExecCode", "input": "df", "assumed": True}
    assert exec_port.columns[2].origin == LineageRef.node_column("x", "output", "q")
    assert exec_port.columns[2].details["template"] == "lineage.observed"

    select_port = ports[("s", "output")]
    assert (select_port.status, select_port.reason) == (PortStatus.PARTIALLY_RESOLVED, DiagnosticReason.LINEAGE_SCHEMA_OBSERVED), "consumers inherit: columns known, origin not"
    assert select_port.names == ("a", "b")
    assert ports[("rn", "output")].names == ("a", "c")
    assert ports[("rn", "output")].column("c").op is LineageOp.RENAME
    assert ports[("w", "df")].status is PortStatus.PARTIALLY_RESOLVED
    assert collect_unresolved_ports(lineage) == (), "observed chains are not reported as unknown"
    assert ports[("rn", "output")].column("a").origin == LineageRef.dataset_field("da", "f-a"), "origin flows through the assumed pass"


def test_observation_never_overrides_a_resolved_port_or_a_disconnected_node():
    observed = {("a", "output"): _observation("a", "zzz"), ("x", "output"): _observation("x", "a", "b")}
    ports, _, _ = _derive(observed)
    assert ports[("a", "output")].names == ("a", "b"), "a resolved seed ignores the observation"

    lonely = snapshot(node("s", "DataFrameSelectColumns", columns=["a"]))
    lineage, _ = derive_project_lineage(
        lonely, port_types=port_types, rules=RULES, seeds={}, observed={("s", "output"): _observation("s", "a")},
    )
    port = lineage.ports[0]
    assert (port.status, port.reason) == (PortStatus.UNRESOLVED, DiagnosticReason.LINEAGE_INPUT_MISSING)

    assert can_use_observation(PortColumns.unresolved(DiagnosticReason.LINEAGE_RULE_MISSING, "x")) is True
    assert can_use_observation(PortColumns.unresolved(DiagnosticReason.LINEAGE_INPUT_INVALID, "x")) is False
    assert can_use_observation(PortColumns()) is False


def test_observed_columns_can_be_described_and_show_up_as_rows():
    _, lineage, _ = _derive({("x", "output"): _observation("x", "a", "b", "q")})
    index = index_lineage("p1", lineage)
    annotation = NodeColumnAnnotation(
        id="an", project_id="p1", node_id="x", port="output", column="q", description="Квота",
        created_at=NOW, updated_at=NOW, description_updated_by="u",
    )
    annotations = {annotation.ref.key: annotation}
    resolver = DescriptionResolver(index, {}, annotations)

    assert resolver.resolve(LineageRef.node_column("x", "output", "q")).provenance is LineageProvenance.DECLARED
    bare = DescriptionResolver(index, {}, {}).resolve(LineageRef.node_column("x", "output", "q"))
    assert (bare.provenance, bare.source) == (LineageProvenance.NONE, LineageRef.node_column("x", "output", "q")), "known column without text: none, with the place to write"
    passed = DescriptionResolver(index, {}, {}).resolve(LineageRef.node_column("rn", "output", "a"))
    assert passed.provenance is LineageProvenance.UNKNOWN, "the assumed pass leads to a field we have no record of"

    groups = group_columns_by_origin(index, resolver, fields={}, datasets={}, annotations=annotations)
    rows = {(row.name, row.start.node_id): row for row in build_column_rows(groups)}
    assert rows[("q", "x")].kind == "node_column" and rows[("q", "x")].origin_node_name == "DataFrameExecCode"
    assert rows[("q", "x")].description.text == "Квота"
    assert rows[("a", "a")].kind == "dataset_field", "pass-through columns stay in their table row"
    assert [item.node_id for item in rows[("a", "a")].occurrences] == ["a", "x", "s", "rn", "w"]


def test_same_name_on_several_inputs_is_not_guessed():
    graph = snapshot(
        node("a", "ReadTableFromDBV3", table_name="deals"),
        node("b", "ReadTableFromDBV3", table_name="users"),
        node("j", "DataFrameJoin", left_on=["id"], right_on=["id"], how="left"),
        node("x", "DataFrameExecCode", code="pass"),
        edges=(edge("a", "j", input="left"), edge("b", "j", input="right"), edge("j", "x")),
    )
    lineage, _ = derive_project_lineage(
        graph, port_types=port_types, rules=RULES,
        seeds={"a": {"output": source_seed("da", "id", "amount")}, "b": {"output": source_seed("db", "id", "name")}},
        observed={("x", "output"): _observation("x", "id", "amount", "name", "total")},
    )
    port = next(item for item in lineage.ports if item.node_id == "x")
    by_name = {column.name: column for column in port.columns}
    assert by_name["id"].op is LineageOp.PASS and by_name["id"].deps == (LineageRef.node_column("j", "output", "id"),)
    assert by_name["amount"].op is LineageOp.PASS
    assert by_name["total"].op is LineageOp.UNKNOWN


def test_join_and_union_downstream_of_an_observed_port_keep_the_observed_reason():
    graph = snapshot(
        node("a", "ReadTableFromDBV3", table_name="deals"),
        node("x", "DataFrameExecCode", code="df['q'] = 1"),
        node("b", "ReadTableFromDBV3", table_name="users"),
        node("j", "DataFrameJoin", left_on=["a"], right_on=["a"], how="left"),
        node("u", "DataFrameUnion", column_mapping={}),
        edges=(edge("a", "x"), edge("x", "j", input="left"), edge("b", "j", input="right"), edge("j", "u", input="df1"), edge("b", "u", input="df2")),
    )
    seeds = {"a": {"output": source_seed("da", "a", "b")}, "b": {"output": source_seed("db", "a", "u")}}

    blind, _ = derive_project_lineage(graph, port_types=port_types, rules=RULES, seeds=seeds)
    blind_join = next(port for port in blind.ports if port.node_id == "j")
    assert (blind_join.status, blind_join.reason, blind_join.detail) == (
        PortStatus.PARTIALLY_RESOLVED, DiagnosticReason.LINEAGE_INPUT_MISSING, "left input lineage is unknown",
    )

    seen, _ = derive_project_lineage(
        graph, port_types=port_types, rules=RULES, seeds=seeds, observed={("x", "output"): _observation("x", "a", "q")},
    )
    ports = {port.node_id: port for port in seen.ports}
    assert (ports["j"].status, ports["j"].reason) == (PortStatus.PARTIALLY_RESOLVED, DiagnosticReason.LINEAGE_SCHEMA_OBSERVED)
    assert ports["j"].names == ("a", "q", "u")
    assert (ports["u"].status, ports["u"].reason) == (PortStatus.PARTIALLY_RESOLVED, DiagnosticReason.LINEAGE_SCHEMA_OBSERVED)
    assert collect_unresolved_ports(seen) == ()
