from unittest.mock import patch

from src.modules.data_catalog.infra import (
    JsonLineageTemplateRenderer,
    NodeDslColumnRulePlanner,
    NodeDslPortTypeGateway,
)

import config


def test_column_rule_planner_plans_split_and_refuses_type_selectors():
    planner = NodeDslColumnRulePlanner()
    rules = [{"id": "r1", "selector": {"tokens": [{"kind": "name", "value": "a"}]}, "params": {"delimiter": "-", "max_splits": 2, "drop_source": True}}]

    planned = planner.plan("split", rules, ["a", "b"])
    assert planned is not None
    assert planned[0].source == "a" and planned[0].targets == ("a_1", "a_2", "a_3") and planned[0].drops_source is True

    typed = [{"id": "r1", "selector": {"tokens": [{"kind": "all"}], "types": ["numeric"]}, "params": {"delimiter": "-"}}]
    assert planner.plan("split", typed, ["a"]) is None
    assert planner.plan("no-such-operation", rules, ["a"]) is None
    assert planner.plan("split", [{"id": "broken"}], ["a"]) is None


def test_expression_rule_exposes_expression_text():
    planner = NodeDslColumnRulePlanner()
    rules = [{"id": "r1", "selector": {"tokens": [{"kind": "name", "value": "a"}]}, "params": {"expression": "a * 2"}, "output": {"mode": "new", "suffix": "_x2"}}]
    planned = planner.plan("expression", rules, ["a", "b"])
    assert planned is not None and planned[0].expression == "a * 2"


def test_port_type_gateway_reads_real_registry_and_caches_misses():
    gateway = NodeDslPortTypeGateway()

    types = gateway.get_port_types("DataFrameJoin")
    assert types is not None
    assert types.dataframe_inputs == frozenset({"left", "right"})
    assert types.dataframe_outputs == ("output",)
    assert types.defaults.get("how") == "left"

    filter_types = gateway.get_port_types("DataFrameFilter")
    assert filter_types is not None and filter_types.dataframe_outputs == ("output", "inverted_output")

    with patch("src.node_dsl.registry.definitions.ensure_ready") as ensure_ready:
        assert gateway.get_port_types("NoSuchNodeEver") is None
        assert ensure_ready.call_count == 1
        assert gateway.get_port_types("NoSuchNodeEver") is None
        assert ensure_ready.call_count == 1, "miss is cached"


def test_template_renderer_falls_back_to_english_and_tolerates_missing_params():
    renderer = JsonLineageTemplateRenderer(config.PROJECT.LOCALES_DIR)
    assert renderer.render("lineage.rename", {"source": "id"}, "ru") == "Переименовано из id"
    assert renderer.render("lineage.rename", {"source": "id"}, "de") == "Renamed from id"
    assert renderer.render("lineage.compute.lag", {}, "en") == "? shifted by ? rows"
    assert renderer.render("lineage.no.such", {}, "en") is None
