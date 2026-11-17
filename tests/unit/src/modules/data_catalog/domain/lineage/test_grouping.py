from __future__ import annotations

from datetime import UTC, datetime

from src.modules.data_catalog.domain import (
    Dataset,
    DatasetField,
    FieldStatus,
    LineageOp,
    LineageProvenance,
    LineageRef,
    NodeColumnAnnotation,
    PortStatus,
    db_table_locator,
)
from src.modules.data_catalog.domain.policies import (
    DescriptionResolver,
    build_builtin_rules,
    build_column_rows,
    collect_orphaned_annotations,
    collect_unresolved_ports,
    column_depth,
    derive_project_lineage,
    group_columns_by_origin,
    index_lineage,
)

from .helpers import edge, node, port_types, snapshot, source_seed

NOW = datetime(2026, 10, 23, tzinfo=UTC)
RULES = build_builtin_rules()


def _field(dataset_id: str, name: str, *, description=None, updated_by=None) -> DatasetField:
    return DatasetField(
        id=f"f-{name}", dataset_id=dataset_id, name=name, status=FieldStatus.OK, first_seen_at=NOW,
        last_seen_at=NOW, description=description, description_updated_by=updated_by,
    )


def _dataset(dataset_id: str, table: str) -> Dataset:
    return Dataset(
        id=dataset_id, organization_id="org", physical_key=f"k-{table}", created_at=NOW, updated_at=NOW,
        locator=db_table_locator("postgresql", "db", 5432, "main", "public", table),
        location=f"main.public.{table} @ db:5432",
    )


def _annotation(node_id: str, column: str, text: str) -> NodeColumnAnnotation:
    return NodeColumnAnnotation(
        id=f"a-{node_id}-{column}", project_id="p1", node_id=node_id, port="output", column=column,
        description=text, created_at=NOW, updated_at=NOW, description_updated_by="analyst",
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
        snap, port_types=port_types, rules=RULES,
        seeds={"a": {"output": source_seed("da", "amount", "cost")}, "b": {"output": source_seed("db", "revenue", "cost")}},
    )
    index = index_lineage("p1", lineage)
    fields = {
        "ds:da:f-amount": _field("da", "amount", description="Выручка", updated_by="dba"),
        "ds:da:f-cost": _field("da", "cost"),
        "ds:db:f-revenue": _field("db", "revenue", description="Выручка"),
        "ds:db:f-cost": _field("db", "cost", description="Другой текст"),
    }
    datasets = {"da": _dataset("da", "a"), "db": _dataset("db", "b")}
    return lineage, index, fields, datasets


def test_groups_follow_origin_and_are_ordered_datasets_first_then_node_columns():
    _, index, fields, datasets = _build()
    groups = group_columns_by_origin(index, DescriptionResolver(index, fields), fields=fields, datasets=datasets, annotations={})

    assert [group.origin.key for group in groups] == [
        "ds:da:f-amount", "ds:da:f-cost", "ds:db:f-cost", "ds:db:f-revenue",
        "node:e:output:ebitda", "node:u:output:cost", "node:u:output:revenue",
    ]
    amount = groups[0]
    assert (amount.kind, amount.dataset_id, amount.dataset_location, amount.field_name) == (
        "dataset_field", "da", "main.public.a @ db:5432", "amount",
    )
    assert [(item.node_id, item.column, item.depth, item.op) for item in amount.occurrences] == [
        ("a", "amount", 1, LineageOp.SOURCE),
        ("rn", "revenue", 2, LineageOp.RENAME),
    ]
    assert (amount.description.text, amount.description.provenance) == ("Выручка", LineageProvenance.DECLARED)
    assert amount.description_updated_by == "dba"
    assert all(item.description.text == "Выручка" and not item.is_override for item in amount.occurrences)

    merged = next(group for group in groups if group.origin.key == "node:u:output:revenue")
    assert (merged.kind, merged.origin_node_name) == ("node_column", "DataFrameUnion")
    assert [(item.node_id, item.depth) for item in merged.occurrences] == [("u", 0), ("e", 1)]
    assert merged.description.provenance is LineageProvenance.INHERITED, "both parents say the same text"

    ebitda = next(group for group in groups if group.origin.key == "node:e:output:ebitda")
    assert ebitda.description.provenance is LineageProvenance.DERIVED and ebitda.override_count == 0


def test_annotation_mid_chain_is_an_override_but_annotation_on_origin_is_not():
    _, index, fields, datasets = _build()
    annotations = {
        "node:rn:output:revenue": _annotation("rn", "revenue", "Выручка по прейскуранту"),
        "node:e:output:ebitda": _annotation("e", "ebitda", "EBITDA"),
    }
    resolver = DescriptionResolver(index, fields, annotations)
    groups = {group.origin.key: group for group in group_columns_by_origin(index, resolver, fields=fields, datasets=datasets, annotations=annotations)}

    amount = groups["ds:da:f-amount"]
    assert (amount.description.text, amount.override_count) == ("Выручка", 1), "the group keeps the origin text"
    by_node = {item.node_id: item for item in amount.occurrences}
    assert by_node["a"].is_override is False
    assert by_node["rn"].is_override is True
    assert (by_node["rn"].description.text, by_node["rn"].description_updated_by) == ("Выручка по прейскуранту", "analyst")

    merged = groups["node:u:output:revenue"]
    assert merged.description.provenance is LineageProvenance.DERIVED, "parents now disagree"

    ebitda = groups["node:e:output:ebitda"]
    assert (ebitda.description.text, ebitda.description.provenance) == ("EBITDA", LineageProvenance.DECLARED)
    assert ebitda.override_count == 0 and ebitda.occurrences[0].is_override is False


def _rows(annotations):
    _, index, fields, datasets = _build()
    resolver = DescriptionResolver(index, fields, annotations)
    groups = group_columns_by_origin(index, resolver, fields=fields, datasets=datasets, annotations=annotations)
    return {(row.name, row.start.node_id): row for row in build_column_rows(groups)}, build_column_rows(groups)


def test_rows_split_on_rename_and_new_origin_but_not_on_pass():
    by_key, rows = _rows({})

    assert [(row.name, row.start.node_id) for row in rows] == [
        ("amount", "a"), ("revenue", "rn"), ("cost", "a"), ("cost", "b"), ("revenue", "b"),
        ("ebitda", "e"), ("cost", "u"), ("revenue", "u"),
    ]
    amount = by_key[("amount", "a")]
    assert [item.node_id for item in amount.occurrences] == ["a"]
    assert amount.is_rename is False and amount.is_refinement is False
    assert [(target.scope, target.node_id, target.field_id) for target in amount.targets] == [
        ("project", "a", None), ("global", None, "f-amount"),
    ]
    assert amount.targets[1].dataset_id == "da" and amount.targets[1].field_name == "amount"

    revenue = by_key[("revenue", "rn")]
    assert (revenue.is_rename, revenue.renamed_from, revenue.is_refinement) == (True, "amount", False)
    assert revenue.description.text == "Выручка" and revenue.description.provenance is LineageProvenance.INHERITED
    assert [target.scope for target in revenue.targets] == ["project"], "only the first table segment may write globally"

    cost = by_key[("cost", "a")]
    assert [item.node_id for item in cost.occurrences] == ["a", "rn"], "pass keeps the segment together"
    assert cost.targets[1].scope == "global"

    ebitda = by_key[("ebitda", "e")]
    assert ebitda.kind == "node_column" and ebitda.targets == (ebitda.targets[0],)
    assert ebitda.targets[0].scope == "project" and ebitda.targets[0].node_id == "e"
    assert set(ebitda.depends_on) == {by_key[("revenue", "u")].id, by_key[("cost", "u")].id}

    merged = by_key[("revenue", "u")]
    assert [item.node_id for item in merged.occurrences] == ["u", "e"]
    assert set(merged.depends_on) == {by_key[("revenue", "rn")].id, by_key[("revenue", "b")].id}


def test_rows_split_on_mid_chain_refinement_and_merge_back_when_it_is_cleared():
    refined, _ = _rows({"node:e:output:cost": _annotation("e", "cost", "Себестоимость после объединения")})

    assert ("cost", "e") in refined, "a description written on a pass column starts a new row"
    refinement = refined[("cost", "e")]
    assert (refinement.is_refinement, refinement.is_rename) == (True, False)
    assert refinement.description.text == "Себестоимость после объединения"
    assert [item.node_id for item in refined[("cost", "u")].occurrences] == ["u"], "the previous row ends before the refinement"
    assert [target.scope for target in refinement.targets] == ["project"]

    plain, _ = _rows({})
    assert ("cost", "e") not in plain
    assert [item.node_id for item in plain[("cost", "u")].occurrences] == ["u", "e"]

    renamed_with_text, _ = _rows({"node:rn:output:revenue": _annotation("rn", "revenue", "Выручка по прейскуранту")})
    row = renamed_with_text[("revenue", "rn")]
    assert (row.is_rename, row.is_refinement) == (True, False), "a rename with its own text is a rename, not a refinement"
    assert row.description.provenance is LineageProvenance.DECLARED

    local_source, _ = _rows({"node:a:output:amount": _annotation("a", "amount", "Только в этом проекте")})
    assert local_source[("amount", "a")].is_refinement is False, "a project-local text on the read column is not a mid-chain refinement"
    assert [target.scope for target in local_source[("amount", "a")].targets] == ["project", "global"]


def test_depth_unresolved_ports_and_orphans():
    lineage, index, _, _ = _build()
    assert column_depth(index, LineageRef.node_column("rn", "output", "revenue"), LineageRef.dataset_field("da", "f-amount")) == 2
    assert column_depth(index, LineageRef.node_column("e", "output", "ebitda"), LineageRef.node_column("e", "output", "ebitda")) == 0
    assert column_depth(index, LineageRef.node_column("e", "output", "ebitda"), LineageRef.dataset_field("da", "f-amount")) == 0, "a compute column stops the walk"
    assert collect_unresolved_ports(lineage) == ()

    orphan = _annotation("rn", "gone", "Колонки больше нет")
    annotations = {"node:rn:output:gone": orphan, "node:rn:output:revenue": _annotation("rn", "revenue", "x")}
    assert collect_orphaned_annotations(index, annotations) == (orphan,)

    dynamic, _ = derive_project_lineage(
        snapshot(node("a", "ReadTableFromDBV3", table_name="a"), node("pv", "DataFramePivot"), edges=(edge("a", "pv"),)),
        port_types=port_types, rules=RULES, seeds={"a": {"output": source_seed("da", "amount")}},
    )
    unresolved = collect_unresolved_ports(dynamic)
    assert [(port.node_id, port.port, port.status) for port in unresolved] == [("pv", "output", PortStatus.UNRESOLVED)]
    assert unresolved[0].reason is not None
