from __future__ import annotations

from src.modules.data_catalog.domain import (
    DiagnosticReason,
    GraphInputValue,
    LineageOp,
    LineageRef,
    PortStatus,
)
from src.modules.data_catalog.domain.policies import (
    build_builtin_rules,
    derive_project_lineage,
    index_lineage,
)

from .helpers import by_name, edge, node, port_types, snapshot, source_seed

RULES = build_builtin_rules()


def _derive(snap, seeds=None, **kwargs):
    lineage, diagnostics = derive_project_lineage(
        snap, port_types=port_types, rules=RULES, seeds=seeds or {}, **kwargs
    )
    return lineage, diagnostics, index_lineage("p1", lineage)


def test_pass_rename_and_sink_chain_keeps_origin_and_snapshots_the_writer():
    snap = snapshot(
        node("r", "ReadTableFromDBV3", table_name="customers"),
        node("f", "DataFrameFilter", conditions={"x": 1}),
        node("rn", "DataFrameRenameColumns", mapping={"id": "customer_id"}),
        node("w", "WriteDataFrameToDBV4", table_name="out"),
        edges=(edge("r", "f"), edge("f", "rn", output="inverted_output"), edge("rn", "w")),
    )
    lineage, diagnostics, index = _derive(snap, {"r": {"output": source_seed("ds", "id", "name")}})

    assert diagnostics == []
    ports = {(p.node_id, p.port): p for p in lineage.ports}
    assert set(ports) == {("r", "output"), ("f", "output"), ("f", "inverted_output"), ("rn", "output"), ("w", "df")}

    renamed = by_name(ports[("rn", "output")])
    assert set(renamed) == {"customer_id", "name"}
    assert renamed["customer_id"].op is LineageOp.RENAME
    assert renamed["customer_id"].deps == (LineageRef.node_column("f", "inverted_output", "id"),)
    assert renamed["customer_id"].origin == LineageRef.dataset_field("ds", "f-id")
    assert renamed["name"].origin == LineageRef.dataset_field("ds", "f-name")

    sink = ports[("w", "df")]
    assert sink.role == "input"
    assert by_name(sink)["customer_id"].origin == LineageRef.dataset_field("ds", "f-id")
    assert index.dependents_of(LineageRef.dataset_field("ds", "f-id"))[0] == LineageRef.node_column("r", "output", "id")


def test_join_renames_right_collisions_and_merges_shared_keys():
    snap = snapshot(
        node("a", "ReadTableFromDBV3", table_name="a"),
        node("b", "ReadTableFromDBV3", table_name="b"),
        node("j", "DataFrameJoin", left_on=["id"], right_on=["id"], how="inner"),
        edges=(edge("a", "j", input="left"), edge("b", "j", input="right")),
    )
    lineage, _, _ = _derive(
        snap, {"a": {"output": source_seed("da", "id", "name", "x")}, "b": {"output": source_seed("db", "id", "name", "y")}}
    )
    joined = by_name(next(p for p in lineage.ports if p.node_id == "j"))

    assert set(joined) == {"id", "name", "x", "name_right", "y"}
    assert joined["id"].op is LineageOp.MERGE and len(joined["id"].deps) == 2
    assert joined["name_right"].op is LineageOp.RENAME
    assert joined["name_right"].deps == (LineageRef.node_column("b", "output", "name"),)
    assert joined["y"].origin == LineageRef.dataset_field("db", "f-y")


def test_join_with_unknown_side_is_partially_resolved():
    snap = snapshot(
        node("a", "ReadTableFromDBV3", table_name="a"),
        node("p", "LoadParquet", path="x.parquet"),
        node("j", "DataFrameJoin", left_on=["id"], right_on=["id"]),
        edges=(edge("a", "j", input="left"), edge("p", "j", input="right")),
    )
    lineage, _, _ = _derive(snap, {"a": {"output": source_seed("da", "id", "x")}})
    ports = {p.node_id: p for p in lineage.ports if p.port == "output"}

    assert ports["p"].status is PortStatus.UNRESOLVED
    assert ports["p"].reason is DiagnosticReason.LINEAGE_SOURCE_NOT_STATIC
    assert ports["j"].status is PortStatus.PARTIALLY_RESOLVED
    assert set(by_name(ports["j"])) == {"id", "x"}


def test_group_by_lag_select_drop_and_expression_rules():
    snap = snapshot(
        node("r", "ReadTableFromDBV3", table_name="orders"),
        node("g", "DataFrameGroupByAgg", group_by_columns=["cust"], new_cols=["total", "n"], source_cols=["amount", "id"], agg_funcs=["sum", "count"]),
        node("l", "DataFrameLagColumns", columns_to_lag=["total"], lag_steps=-2),
        node("e", "DataFrameAddColumnByExpression", column_name="score", expression="total * 2 + `n`"),
        node("s", "DataFrameSelectColumns", columns=["cust", "score", "missing"]),
        node("d", "DataFrameDropColumns", columns=["cust"]),
        edges=(edge("r", "g"), edge("g", "l"), edge("l", "e"), edge("e", "s"), edge("s", "d")),
    )
    lineage, diagnostics, _ = _derive(snap, {"r": {"output": source_seed("ds", "id", "cust", "amount")}})
    ports = {p.node_id: by_name(p) for p in lineage.ports}

    assert diagnostics == []
    assert set(ports["g"]) == {"cust", "total", "n"}
    assert ports["g"]["total"].op is LineageOp.AGGREGATE
    assert ports["g"]["total"].details["function"] == "sum"
    assert ports["g"]["cust"].origin == LineageRef.dataset_field("ds", "f-cust")
    assert set(ports["l"]) == {"cust", "total", "n", "total_lag-2"}
    assert ports["l"]["total_lag-2"].deps == (LineageRef.node_column("g", "output", "total"),)
    assert ports["e"]["score"].op is LineageOp.COMPUTE
    assert {dep.column for dep in ports["e"]["score"].deps} == {"total", "n"}
    assert set(ports["s"]) == {"cust", "score"}
    assert set(ports["d"]) == {"score"}
    assert ports["d"]["score"].origin == LineageRef.node_column("e", "output", "score")


def test_union_merges_mapped_columns_and_passes_unique_ones():
    snap = snapshot(
        node("a", "ReadTableFromDBV3", table_name="a"),
        node("b", "ReadTableFromDBV3", table_name="b"),
        node("u", "DataFrameUnion", column_mapping={"id": "ident", "only_a": "nope"}),
        edges=(edge("a", "u", input="df1"), edge("b", "u", input="df2")),
    )
    lineage, _, _ = _derive(snap, {"a": {"output": source_seed("da", "id", "only_a")}, "b": {"output": source_seed("db", "ident", "only_b")}})
    union = by_name(next(p for p in lineage.ports if p.node_id == "u"))

    assert set(union) == {"id", "only_a", "only_b"}
    assert union["id"].op is LineageOp.MERGE
    assert {dep.key for dep in union["id"].deps} == {"node:a:output:id", "node:b:output:ident"}
    assert union["only_b"].op is LineageOp.PASS


def test_dynamic_inputs_missing_rules_and_cycles_are_diagnosed():
    snap = snapshot(
        node("r", "ReadTableFromDBV3", table_name="t"),
        node("sel", "DataFrameSelectColumns", columns=GraphInputValue.expr("{{ x }}", "template")),
        node("pv", "DataFramePivot", index="a", column="b"),
        node("x", "UnknownNode"),
        node("c1", "DataFrameQuery", query="a > 1"),
        node("c2", "DataFrameQuery", query="b > 1"),
        edges=(edge("r", "sel"), edge("sel", "pv"), edge("c1", "c2"), edge("c2", "c1")),
    )
    lineage, diagnostics, _ = _derive(snap, {"r": {"output": source_seed("ds", "a", "b")}})
    ports = {p.node_id: p for p in lineage.ports}

    assert ports["sel"].status is PortStatus.UNRESOLVED and ports["sel"].reason is DiagnosticReason.LINEAGE_INPUT_DYNAMIC
    assert ports["pv"].reason is DiagnosticReason.LINEAGE_INPUT_DYNAMIC
    assert ports["c1"].reason is DiagnosticReason.LINEAGE_CYCLE and ports["c2"].reason is DiagnosticReason.LINEAGE_CYCLE
    reasons = {(d.node_id, d.reason) for d in diagnostics}
    assert ("x", DiagnosticReason.LINEAGE_NODE_DEFINITION_MISSING) in reasons
    assert ("c1", DiagnosticReason.LINEAGE_CYCLE) in reasons


def test_duplicate_and_internal_columns_are_dropped_and_ports_are_truncated():
    snap = snapshot(node("r", "ReadTableFromDBV3", table_name="t"), node("q", "DataFrameQuery", query="1"), edges=(edge("r", "q"),))
    seed = source_seed("ds", "a", "__dvt_partition", "b", "c")
    lineage, diagnostics, _ = _derive(snap, {"r": {"output": seed}}, max_columns_per_port=2)

    read = next(p for p in lineage.ports if p.node_id == "r")
    assert [c.name for c in read.columns] == ["a", "b"]
    assert lineage.truncated is True
    assert any(d.reason is DiagnosticReason.LINEAGE_TRUNCATED for d in diagnostics)
