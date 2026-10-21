from __future__ import annotations

from datetime import UTC, datetime

from src.modules.data_catalog.domain import (
    DatasetField,
    ExplainDirection,
    FieldStatus,
    LineageOp,
    LineageProvenance,
    LineageRef,
)
from src.modules.data_catalog.domain.policies import (
    DescriptionResolver,
    build_builtin_rules,
    collect_dependents,
    derive_project_lineage,
    explain,
    index_lineage,
)

from .helpers import edge, node, port_types, snapshot, source_seed

NOW = datetime(2026, 10, 20, tzinfo=UTC)
RULES = build_builtin_rules()


def _field(dataset_id: str, name: str, *, description=None, comment=None) -> DatasetField:
    return DatasetField(
        id=f"f-{name}",
        dataset_id=dataset_id,
        name=name,
        status=FieldStatus.OK,
        first_seen_at=NOW,
        last_seen_at=NOW,
        description=description,
        source_comment=comment,
    )


def _build():
    snap = snapshot(
        node("a", "ReadTableFromDBV3", table_name="a"),
        node("b", "ReadTableFromDBV3", table_name="b"),
        node("rn", "DataFrameRenameColumns", mapping={"amount": "revenue"}),
        node("u", "DataFrameUnion", column_mapping={}),
        node("e", "DataFrameAddColumnByExpression", column_name="ebitda", expression="revenue - cost"),
        edges=(edge("a", "rn"), edge("rn", "u", input="df1"), edge("b", "u", input="df2"), edge("u", "e")),
    )
    lineage, _ = derive_project_lineage(
        snap,
        port_types=port_types,
        rules=RULES,
        seeds={"a": {"output": source_seed("da", "amount", "cost")}, "b": {"output": source_seed("db", "revenue", "cost")}},
    )
    index = index_lineage("p1", lineage)
    fields = {
        "ds:da:f-amount": _field("da", "amount", description="Выручка"),
        "ds:da:f-cost": _field("da", "cost", comment="Себестоимость из 1С"),
        "ds:db:f-revenue": _field("db", "revenue", description="Выручка"),
        "ds:db:f-cost": _field("db", "cost", description="Другой текст"),
    }
    return index, fields


def test_descriptions_are_inherited_through_rename_and_equal_merge_only():
    index, fields = _build()
    resolver = DescriptionResolver(index, fields)

    renamed = resolver.resolve(LineageRef.node_column("rn", "output", "revenue"))
    assert (renamed.text, renamed.provenance) == ("Выручка", LineageProvenance.INHERITED)
    assert renamed.source == LineageRef.dataset_field("da", "f-amount")

    merged_equal = resolver.resolve(LineageRef.node_column("u", "output", "revenue"))
    assert (merged_equal.text, merged_equal.provenance) == ("Выручка", LineageProvenance.INHERITED)

    merged_diff = resolver.resolve(LineageRef.node_column("u", "output", "cost"))
    assert merged_diff.provenance is LineageProvenance.DERIVED and merged_diff.text is None

    computed = resolver.resolve(LineageRef.node_column("e", "output", "ebitda"))
    assert computed.provenance is LineageProvenance.DERIVED

    from_comment = resolver.resolve(LineageRef.node_column("rn", "output", "cost"))
    assert (from_comment.text, from_comment.provenance) == ("Себестоимость из 1С", LineageProvenance.INHERITED)
    assert resolver.resolve(LineageRef.dataset_field("da", "f-cost")).provenance is LineageProvenance.SOURCE


def test_explain_upstream_reaches_sources_and_respects_depth():
    index, fields = _build()
    root = LineageRef.node_column("e", "output", "ebitda")

    full = explain(index, root, direction=ExplainDirection.UPSTREAM, max_depth=10, render=lambda d: d.get("template"), fields=fields)
    ops = [(step.depth, step.op) for step in full.steps]
    assert ops[0] == (0, LineageOp.COMPUTE)
    assert {step.field_name for step in full.steps if step.op is LineageOp.SOURCE and step.dataset_id} >= {"amount", "revenue", "cost"}
    assert full.truncated is False and full.gaps == ()
    assert [dep.key for dep in full.steps[0].deps] == ["node:u:output:revenue", "node:u:output:cost"]
    assert all(step.deps == () for step in full.steps if step.op is LineageOp.SOURCE and step.dataset_id)

    shallow = explain(index, root, direction=ExplainDirection.UPSTREAM, max_depth=1, render=lambda d: None)
    assert shallow.truncated is True
    assert max(step.depth for step in shallow.steps) == 1


def test_downstream_and_dependents_follow_reverse_edges():
    index, _ = _build()
    source = LineageRef.dataset_field("da", "f-amount")

    dependents = collect_dependents(index, source, max_depth=10)
    assert [(d.node_id, d.column, d.depth) for d in dependents] == [
        ("a", "amount", 1),
        ("rn", "revenue", 2),
        ("u", "revenue", 3),
        ("e", "revenue", 4),
        ("e", "ebitda", 4),
    ]

    downstream = explain(index, source, direction=ExplainDirection.DOWNSTREAM, max_depth=2, render=lambda d: None)
    assert [step.ref.key for step in downstream.steps][:3] == ["ds:da:f-amount", "node:a:output:amount", "node:rn:output:revenue"]
    assert downstream.truncated is True
