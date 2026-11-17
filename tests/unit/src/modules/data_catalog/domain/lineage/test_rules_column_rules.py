from __future__ import annotations

from src.modules.data_catalog.domain import (
    LineageOp,
    LineageRef,
    PlannedRuleColumn,
    PortLineage,
    PortStatus,
)
from src.modules.data_catalog.domain.policies import RuleContext, build_builtin_rules

from .helpers import PORT_TYPES, by_name, node, source_seed


class FakePlanner:
    def __init__(self, planned=None, *, none=False):
        self.planned = planned or ()
        self.none = none
        self.calls = []

    def plan(self, operation, rules, columns):
        self.calls.append((operation, tuple(columns)))
        return None if self.none else tuple(self.planned)


def _upstream(*names: str) -> PortLineage:
    seed = source_seed("ds", *names)
    columns = tuple(c.with_origin(c.deps[0]) for c in seed.columns)
    return PortLineage(node_id="r", node_name="ReadTableFromDBV3", port="output", status=PortStatus.RESOLVED, columns=columns)


def _run(node_obj, planner=None, upstream=None):
    rules = build_builtin_rules(planner)
    rule = rules.get(node_obj.name)
    assert rule is not None
    ctx = RuleContext(node=node_obj, inputs={"df": upstream or _upstream("a", "b")}, port_types=PORT_TYPES[node_obj.name], planner=planner)
    return rule(ctx)["output"]


def test_split_rule_plan_creates_parts_and_drops_source():
    planner = FakePlanner([PlannedRuleColumn(source="a", targets=("a_1", "a_2"), drops_source=True)])
    port = _run(node("s", "DataFrameSplitColumn", column_rules=[{"id": "r"}]), planner)
    columns = by_name(port)

    assert planner.calls == [("split", ("a", "b"))]
    assert set(columns) == {"b", "a_1", "a_2"}
    assert columns["a_1"].op is LineageOp.COMPUTE
    assert columns["a_1"].deps == (LineageRef.node_column("r", "output", "a"),)


def test_replace_in_place_keeps_pass_semantics_and_new_target_is_computed():
    planner = FakePlanner([PlannedRuleColumn(source="a", targets=("a",)), PlannedRuleColumn(source="b", targets=("b_clean",))])
    columns = by_name(_run(node("x", "DataFrameReplaceValues", column_rules=[{"id": "r"}]), planner))

    assert columns["a"].op is LineageOp.PASS and columns["a"].details["template"] == "lineage.pass.transformed"
    assert columns["b_clean"].op is LineageOp.COMPUTE and columns["b_clean"].details["operation"] == "replace"


def test_expression_rule_extracts_dependencies_from_plan():
    planner = FakePlanner([PlannedRuleColumn(source="a", targets=("sum",), expression="a + b")])
    columns = by_name(_run(node("e", "DataFrameAddColumnByExpression", column_rules=[{"id": "r"}]), planner))

    assert {dep.column for dep in columns["sum"].deps} == {"a", "b"}
    assert columns["sum"].deps_unknown is False


def test_unplannable_rules_and_missing_planner_are_unresolved():
    unplannable = _run(node("s", "DataFrameSplitColumn", column_rules=[{"id": "r"}]), FakePlanner(none=True))
    assert unplannable.status is PortStatus.UNRESOLVED

    no_planner = _run(node("s", "DataFrameSplitColumn", column_rules=[{"id": "r"}]), None)
    assert no_planner.status is PortStatus.UNRESOLVED


def test_legacy_modes_without_rules_use_node_inputs():
    split = by_name(_run(node("s", "DataFrameSplitColumn", column="a", max_splits=2, drop_source=True)))
    assert set(split) == {"b", "a_1", "a_2", "a_3"}

    period = by_name(_run(node("p", "DataFrameConvertToPeriodStart", column="a", new_column="a_month")))
    assert period["a_month"].op is LineageOp.COMPUTE and period["a"].op is LineageOp.PASS

    in_place = by_name(_run(node("t", "DataFrameSetTimezone", column="a", timezone="UTC")))
    assert in_place["a"].details["template"] == "lineage.pass.transformed"

    calculated = by_name(
        _run(node("e", "DataFrameAddColumnByExpression", calculated_columns=[{"name": "c", "expression": "a*2"}, {"name": "d", "expression": "b", "input_bindings": {"x": "y"}}]))
    )
    assert calculated["c"].deps == (LineageRef.node_column("r", "output", "a"),)
    assert calculated["d"].deps_unknown is True
