from __future__ import annotations

from datetime import UTC, datetime

from src.modules.data_catalog.domain import (
    DatasetField,
    ExplainDirection,
    FieldStatus,
    LineageOp,
    LineageProvenance,
    LineageRef,
    NodeColumnAnnotation,
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


def _annotation(node_id: str, column: str, text: str) -> NodeColumnAnnotation:
    return NodeColumnAnnotation(
        id=f"a-{node_id}-{column}", project_id="p1", node_id=node_id, port="output", column=column,
        description=text, created_at=NOW, updated_at=NOW, description_updated_by="u",
    )


def test_annotations_win_over_inheritance_and_are_inherited_downstream():
    index, fields = _build()
    annotations = {
        "node:rn:output:revenue": _annotation("rn", "revenue", "Выручка по прейскуранту"),
        "node:u:output:cost": _annotation("u", "cost", "Себестоимость после объединения"),
        "node:e:output:ebitda": _annotation("e", "ebitda", "EBITDA = выручка - себестоимость"),
    }
    resolver = DescriptionResolver(index, fields, annotations)

    overridden = resolver.resolve(LineageRef.node_column("rn", "output", "revenue"))
    assert (overridden.text, overridden.provenance) == ("Выручка по прейскуранту", LineageProvenance.DECLARED)
    assert overridden.source == LineageRef.node_column("rn", "output", "revenue")

    merged = resolver.resolve(LineageRef.node_column("u", "output", "cost"))
    assert merged.provenance is LineageProvenance.DECLARED, "annotation replaces the derived verdict of a mixed merge"

    passed_down = resolver.resolve(LineageRef.node_column("e", "output", "cost"))
    assert (passed_down.text, passed_down.provenance) == ("Себестоимость после объединения", LineageProvenance.INHERITED)
    assert passed_down.source == LineageRef.node_column("u", "output", "cost")

    computed = resolver.resolve(LineageRef.node_column("e", "output", "ebitda"))
    assert (computed.text, computed.provenance) == ("EBITDA = выручка - себестоимость", LineageProvenance.DECLARED)

    untouched = resolver.resolve(LineageRef.node_column("u", "output", "revenue"))
    assert untouched.provenance is LineageProvenance.DERIVED, "texts of the merge parents now differ"


def test_field_without_text_yields_none_with_a_known_source():
    index, fields = _build()
    fields["ds:db:f-cost"] = _field("db", "cost")
    resolver = DescriptionResolver(index, fields)

    field = resolver.resolve(LineageRef.dataset_field("db", "f-cost"))
    assert (field.text, field.provenance, field.source) == (None, LineageProvenance.NONE, LineageRef.dataset_field("db", "f-cost"))

    read = resolver.resolve(LineageRef.node_column("b", "output", "cost"))
    assert (read.provenance, read.source) == (LineageProvenance.NONE, LineageRef.dataset_field("db", "f-cost"))

    merged = resolver.resolve(LineageRef.node_column("u", "output", "cost"))
    assert (merged.text, merged.provenance) == ("Себестоимость из 1С", LineageProvenance.INHERITED), "an empty side is not a conflict"
    assert merged.source == LineageRef.dataset_field("da", "f-cost")
    assert resolver.resolve(LineageRef.node_column("x", "output", "nothing")).provenance is LineageProvenance.UNKNOWN


def test_join_key_inherits_the_only_described_side_and_stays_derived_on_conflict():
    snap = snapshot(
        node("a", "ReadTableFromDBV3", table_name="deals"),
        node("b", "ReadTableFromDBV3", table_name="statuses"),
        node("f", "DataFrameFilter", query="x > 0"),
        node("j", "DataFrameJoin", left_on=["ENTITY_ID"], right_on=["ENTITY_ID"], how="left"),
        edges=(edge("a", "f"), edge("f", "j", input="left"), edge("b", "j", input="right")),
    )
    lineage, _ = derive_project_lineage(
        snap, port_types=port_types, rules=RULES,
        seeds={"a": {"output": source_seed("da", "ENTITY_ID", "amount")}, "b": {"output": source_seed("db", "ENTITY_ID", "status")}},
    )
    index = index_lineage("p1", lineage)
    fields = {
        "ds:da:f-ENTITY_ID": _field("da", "ENTITY_ID"),
        "ds:da:f-amount": _field("da", "amount"),
        "ds:db:f-ENTITY_ID": _field("db", "ENTITY_ID"),
        "ds:db:f-status": _field("db", "status", description="Статус сделки"),
    }
    key = LineageRef.node_column("j", "output", "ENTITY_ID")
    assert index.column(key)[1].op is LineageOp.MERGE, "same-name join keys are merged"

    annotated = {"node:f:output:ENTITY_ID": NodeColumnAnnotation(
        id="a1", project_id="p1", node_id="f", port="output", column="ENTITY_ID", description="Тест",
        created_at=NOW, updated_at=NOW,
    )}
    one_side = DescriptionResolver(index, fields, annotated).resolve(key)
    assert (one_side.text, one_side.provenance) == ("Тест", LineageProvenance.INHERITED)
    assert one_side.source == LineageRef.node_column("f", "output", "ENTITY_ID")

    fields["ds:db:f-ENTITY_ID"] = _field("db", "ENTITY_ID", description="ID контрагента")
    conflict = DescriptionResolver(index, fields, annotated).resolve(key)
    assert (conflict.text, conflict.provenance) == (None, LineageProvenance.DERIVED), "two different texts are a real conflict"

    nobody = DescriptionResolver(index, {k: _field("da" if k.startswith("ds:da") else "db", k.rsplit("-", 1)[1]) for k in fields}).resolve(key)
    assert nobody.provenance is LineageProvenance.DERIVED and nobody.text is None


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
