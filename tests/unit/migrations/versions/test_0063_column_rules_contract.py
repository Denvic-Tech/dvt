import importlib
from copy import deepcopy

import dask.dataframe as dd
import pandas as pd
import pytest
import sqlalchemy as sa

from src.node_dsl.registry.definitions import _create_node_base_definition
from src.pipeline.graph_utils import build_node_kwargs
from src.schemas.internal.node_data import NodeData

migration = importlib.import_module("migrations.versions.0063_column_rules_contract")
const = migration.const
CASES = [
    (
        "df_replace_values",
        "DataFrameReplaceValues",
        {"column_to_replace": "text", "dictionary": {"": "missing", "a-b": "x"}},
    ),
    (
        "df_replace_values",
        "DataFrameReplaceValues",
        {"column_to_replace": "text", "dictionary": {}},
    ),
    (
        "df_regex_replace",
        "DataFrameRegexReplace",
        {"column_to_replace": "text", "pattern": "", "replacement": "."},
    ),
    ("df_set_timezone", "DataFrameSetTimezone", {"column": "date", "timezone": "UTC"}),
    (
        "df_convert_to_period_start",
        "DataFrameConvertToPeriodStart",
        {"column": "date", "period": "month", "new_column": "existing"},
    ),
    (
        "df_convert_to_period_start",
        "DataFrameConvertToPeriodStart",
        {"column": "date", "period": "day"},
    ),
    (
        "df_add_time_delta",
        "AddTimeDeltaToDataFrame",
        {
            "column_with_time": "date",
            "new_column_with_time": "existing",
            "days": 1.9,
            "hours": -1.8,
            "weeks": 42,
        },
    ),
    (
        "df_split_columns",
        "DataFrameSplitColumn",
        {"column": "text", "delimiter": "-", "max_splits": 2, "drop_source": True},
    ),
    (
        "df_add_column_by_expression",
        "DataFrameAddColumnByExpression",
        {"column_name": "existing", "expression": "n * 2"},
    ),
    (
        "df_add_column_by_expression",
        "DataFrameAddColumnByExpression",
        {"column_name": "new", "expression": "__column__ + n"},
    ),
    ("df_set_column_to_dataframe", "SetColumnToDataFrame", {"column_name": "existing"}),
]


def frame():
    return dd.from_pandas(
        pd.DataFrame(
            {
                "text": ["a-b", None, "c"],
                "n": [1, 2, 3],
                "__column__": [10, 20, 30],
                "date": pd.Series(pd.to_datetime(["2026-01-15", "2026-02-28", None])).astype(
                    "datetime64[us]"
                ),
                "existing": [0, 0, 0],
            },
            index=[0, 1, 2],
        ),
        npartitions=2,
    )


def node_class(package, name):
    return getattr(importlib.import_module("src.nodes.transform." + package), name)


def kwargs(cls, values, **extra):
    return build_node_kwargs(
        node_id="n",
        node_def=_create_node_base_definition(cls),
        node_class=cls,
        node_data=NodeData(name=cls.__name__, inputs=values),
        node_outputs={},
        **extra,
    )


async def run(cls, values, **extra):
    node = cls(
        user_id="u",
        project_id="p",
        task_id="t",
        node_id="n",
        df=frame(),
        **kwargs(cls, values, **extra),
    )
    if cls.__name__ == "SetColumnToDataFrame":
        node.column_data = dd.from_pandas(pd.Series([4, 5, 6], name=None), npartitions=2)
    await node.validate()
    node.process()
    return node.output.compute()


@pytest.mark.asyncio
@pytest.mark.parametrize("package,name,inputs", CASES)
async def test_upgrade_preserves_values_dtypes_and_index(package, name, inputs):
    cls = node_class(package, name)
    original = {key: const(value) for key, value in inputs.items()}
    saved = deepcopy(original)
    migrated, changed = migration.upgrade_inputs(name, original)
    assert changed
    assert original == saved
    pd.testing.assert_frame_equal(await run(cls, original), await run(cls, migrated))
    assert migration.upgrade_inputs(name, migrated) == (migrated, False)
    restored, changed = migration.downgrade_inputs(name, migrated)
    assert changed and restored == original
    assert migration.upgrade_inputs(name, restored)[0] == migrated


@pytest.mark.asyncio
async def test_expressions_are_resolved_again_on_every_execution():
    cls = node_class("df_add_time_delta", "AddTimeDeltaToDataFrame")
    original = {
        "column_with_time": {"__dvt_type": "expr", "value": "source", "expression_kind": "single"},
        "new_column_with_time": const("existing"),
        "days": {"__dvt_type": "expr", "value": "offset", "expression_kind": "single"},
    }
    migrated, changed = migration.upgrade_inputs(cls.__name__, original)
    assert changed
    for days in (1.9, -2.8):
        variables = {"source": "date", "offset": days}
        pd.testing.assert_frame_equal(
            await run(cls, original, project_variables=variables),
            await run(cls, migrated, project_variables=variables),
        )


@pytest.mark.parametrize(
    "raw", [None, {}, "{broken", '{"column": {"__dvt_type": "const", "value": "date"}}']
)
def test_empty_and_old_json_payloads_roundtrip(raw):
    migrated, changed = migration.upgrade_inputs("DataFrameSetTimezone", raw)
    assert changed and "column_rules" in migrated
    restored, changed = migration.downgrade_inputs("DataFrameSetTimezone", migrated)
    assert changed and restored == raw


def test_existing_new_contract_and_edits_are_never_overwritten():
    original = {"column": const("date"), "timezone": const("UTC")}
    migrated, _ = migration.upgrade_inputs("DataFrameSetTimezone", original)
    migrated["column_rules"]["value"][0]["params"]["timezone"] = "Europe/Moscow"
    assert migration.downgrade_inputs("DataFrameSetTimezone", migrated) == (migrated, False)
    assert migration.upgrade_inputs("DataFrameSetTimezone", migrated) == (migrated, False)
    assert migration.upgrade_inputs("DataFrameSetTimezone", {"column_rules": const([])})[1] is False


def test_database_upgrade_downgrade_batches_and_project_scoped_edges(monkeypatch):
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    nodes = sa.Table(
        "graph_nodes",
        metadata,
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("name", sa.String),
        sa.Column("ui_id", sa.String),
        sa.Column("project_id", sa.String),
        sa.Column("input_values", sa.JSON),
    )
    edges = sa.Table(
        "graph_edges",
        metadata,
        sa.Column("project_id", sa.String),
        sa.Column("target", sa.String),
        sa.Column("target_handle", sa.String),
    )
    metadata.create_all(engine)
    rows = [
        {
            "id": f"{i:04d}",
            "name": "DataFrameSetTimezone",
            "ui_id": "same",
            "project_id": f"p{i}",
            "input_values": {"column": const("date")},
        }
        for i in range(503)
    ]
    rows.append(
        {
            "id": "other",
            "name": "OtherNode",
            "ui_id": "same",
            "project_id": "other",
            "input_values": {"column": const("untouched")},
        }
    )
    with engine.begin() as connection:
        connection.execute(nodes.insert(), rows)
        connection.execute(
            edges.insert(),
            [{"project_id": "p1", "target": "same", "target_handle": "input-column"}],
        )
        monkeypatch.setattr(migration.op, "get_bind", lambda: connection)
        migration.upgrade()
        upgraded = dict(connection.execute(sa.select(nodes.c.id, nodes.c.input_values)).all())
        assert "column_rules" not in upgraded["other"]
        assert all("column_rules" in upgraded[f"{i:04d}"] for i in range(503))
        assert upgraded["0001"]["column_rules"]["value"][0]["input_bindings"] == {
            "selector.tokens.0.value": "column"
        }
        assert upgraded["0000"]["column_rules"]["value"][0]["input_bindings"] == {}
        migration.upgrade()
        assert (
            dict(connection.execute(sa.select(nodes.c.id, nodes.c.input_values)).all()) == upgraded
        )
        migration.downgrade()
        assert dict(connection.execute(sa.select(nodes.c.id, nodes.c.input_values)).all()) == {
            row["id"]: row["input_values"] for row in rows
        }
        migration.upgrade()
        assert (
            dict(connection.execute(sa.select(nodes.c.id, nodes.c.input_values)).all()) == upgraded
        )


@pytest.mark.asyncio
async def test_migrated_replacement_can_be_edited_as_new_pairs():
    cls = node_class("df_replace_values", "DataFrameReplaceValues")
    migrated, _ = migration.upgrade_inputs(
        cls.__name__,
        {
            "column_to_replace": const("text"),
            "dictionary": const({"a-b": "old"}),
        },
    )
    params = migrated["column_rules"]["value"][0]["params"]
    params.pop("legacy_dictionary")
    params["pairs"] = [{"old": "a-b", "new": "edited"}]
    assert (await run(cls, migrated))["text"].iloc[0] == "edited"


@pytest.mark.asyncio
async def test_linked_inputs_keep_connections_and_runtime_values():
    from src.node_dsl.types import NodeOutput

    cls = node_class("df_regex_replace", "DataFrameRegexReplace")
    original = {
        "column_to_replace": {"__dvt_type": "link", "node_id": "source", "output_name": "column"},
        "pattern": const("a"),
        "replacement": const("z"),
    }
    migrated, _ = migration.upgrade_inputs(cls.__name__, original)
    assert migrated["column_to_replace"] == original["column_to_replace"]
    outputs = {"source": {"column": NodeOutput(value="text")}}
    definition = _create_node_base_definition(cls)
    for values in (original, migrated):
        resolved = build_node_kwargs(
            node_id="n",
            node_def=definition,
            node_data=NodeData(name=cls.__name__, inputs=values),
            node_outputs=outputs,
        )
        node = cls(user_id="u", project_id="p", task_id="t", node_id="n", df=frame(), **resolved)
        await node.validate()
        node.process()
        assert node.output.compute()["text"].iloc[0] == "z-b"


def test_previous_definition_ignores_new_contract_fields():
    cls = node_class("df_regex_replace", "DataFrameRegexReplace")
    original = {
        "column_to_replace": const("text"),
        "pattern": const("a"),
        "replacement": const("z"),
    }
    migrated, _ = migration.upgrade_inputs(cls.__name__, original)
    definition = _create_node_base_definition(cls)
    definition.input_definitions.pop("column_rules")

    def resolve(values):
        return build_node_kwargs(
            node_id="n",
            node_def=definition,
            node_data=NodeData(name=cls.__name__, inputs=values),
            node_outputs={},
        )

    assert resolve(migrated) == resolve(original)


def test_roundtrip_preserves_other_edits_to_old_string_payload():
    original = '{"column": {"__dvt_type": "const", "value": "date"}}'
    migrated, _ = migration.upgrade_inputs("DataFrameSetTimezone", original)
    migrated["timezone"] = const("UTC")
    restored, changed = migration.downgrade_inputs("DataFrameSetTimezone", migrated)
    assert changed
    assert restored == {"column": const("date"), "timezone": const("UTC")}


def test_reupgrade_does_not_resurrect_a_cleared_contract():
    migrated, _ = migration.upgrade_inputs("DataFrameSetTimezone", {"column": const("date")})
    migrated["column_rules"] = const(None)
    assert migration.downgrade_inputs("DataFrameSetTimezone", migrated) == (migrated, False)
    assert migration.upgrade_inputs("DataFrameSetTimezone", migrated) == (migrated, False)


@pytest.mark.asyncio
async def test_migrated_delta_still_rejects_non_temporal_source():
    from src.node_dsl import NodeValidationError

    cls = node_class("df_add_time_delta", "AddTimeDeltaToDataFrame")
    original = {"column_with_time": const("n"), "new_column_with_time": const("new")}
    migrated, _ = migration.upgrade_inputs(cls.__name__, original)
    for values in (original, migrated):
        with pytest.raises(NodeValidationError):
            await run(cls, values)


@pytest.mark.asyncio
async def test_detached_binding_no_longer_evaluates_retained_expression():
    cls = node_class("df_regex_replace", "DataFrameRegexReplace")
    original = {
        "column_to_replace": const("text"),
        "pattern": {"__dvt_type": "expr", "value": "removed_variable", "expression_kind": "single"},
        "replacement": const("z"),
    }
    migrated, _ = migration.upgrade_inputs(cls.__name__, original)
    rule = migrated["column_rules"]["value"][0]
    rule["params"]["pattern"] = "a"
    rule["input_bindings"].pop("params.pattern")
    assert (await run(cls, migrated))["text"].iloc[0] == "z-b"
    assert migrated["pattern"] == original["pattern"]  # still available on rollback
