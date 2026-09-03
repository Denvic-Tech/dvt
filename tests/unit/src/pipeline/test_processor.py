import asyncio

import dask.dataframe as dd
import pandas as pd
import pytest
import sqlalchemy as sa

from core.types import DataFrameMetadata

from src.modules.pipeline_cache import MetadataCacheEntry, create_node_inputs_fingerprint
from src.node_dsl import IO, DFOutputBaseNode, InputField, JSONOutputBaseNode, OutputField
from src.node_dsl.core.input_values import NodeInputConstantValue, NodeInputLinkValue
from src.node_dsl.types import NodeOutput
from src.node_dsl.variables import UnresolvedValue
from src.nodes.extract.read_query_from_db_v3 import ReadQueryFromDBV3
from src.nodes.primitive.create_variable import CreateVariable
from src.nodes.primitive.manage_variables import ManageVariables
from src.nodes.testing.simple_input import SimpleInputNode
from src.nodes.testing.simple_output import SimpleOutputNode
from src.nodes.tool.conditional_signal_router import ConditionalSignalRouter
from src.nodes.transform.df_filter import DataFrameFilter
from src.nodes.transform.df_select_variables import DataFrameSelectVariables
from src.nodes.write.write_df_to_db_v3 import WriteDataFrameToDBV3
from src.pipeline.execution_mode import PipelineExecutionMode
from src.pipeline.processor import PipelineProcessor
from src.schemas.internal import (
    NodeData,
    ProjectSettings,
    ProjectVariables,
    TaskInternal,
)


class AsyncMetadataNode(JSONOutputBaseNode):
    output: IO.JSON = OutputField()
    infer_metadata_calls = 0

    def process(self) -> None:
        self.output = {"status": "ok"}

    async def infer_metadata(self):
        type(self).infer_metadata_calls += 1
        return {"output": {"kind": "async-metadata"}}


class MetadataSeedDataFrameNode(DFOutputBaseNode):
    output: dd.DataFrame = OutputField()

    def process(self) -> None:
        pdf = pd.DataFrame(
            {
                "ctx_value": ["alpha", "beta"],
                "ctx_int": [1, 2],
            }
        )
        self.output = dd.from_pandas(pdf, npartitions=1)


class CacheFrontierDataFrameNode(DFOutputBaseNode):
    df_in: dd.DataFrame = InputField()
    output: dd.DataFrame = OutputField()

    def process(self) -> None:
        self.output = self.df_in


def _register_nodes(*node_classes) -> None:
    from src.node_dsl.registry import (
        nodes as nodes_registry,
        definitions as definitions_registry,
        hooks as hooks_registry,
    )

    for node_cls in node_classes:
        if node_cls.__name__ not in nodes_registry.get_all():
            nodes_registry.add(node_cls)
        if node_cls.__name__ not in definitions_registry.NODE_DEFINITIONS:
            definitions_registry.build(node_cls)
        hooks_registry.build(node_cls)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "restorable_node_id", "expected_execution_order"),
    [
        (PipelineExecutionMode.FULL, "frontier", ["changed"]),
        (PipelineExecutionMode.FULL, "source", ["frontier", "changed"]),
        (PipelineExecutionMode.METADATA_ONLY, "frontier", ["changed"]),
    ],
)
async def test_pipeline_processor_builds_nearest_complete_cache_frontier(
    monkeypatch,
    mode,
    restorable_node_id,
    expected_execution_order,
) -> None:
    _register_nodes(MetadataSeedDataFrameNode, CacheFrontierDataFrameNode)
    pipeline = {
        "source": NodeData(
            name="MetadataSeedDataFrameNode",
            inputs={},
            store_enabled=True,
        ),
        "frontier": NodeData(
            name="CacheFrontierDataFrameNode",
            inputs={
                "df_in": NodeInputLinkValue(node_id="source", output_name="output"),
            },
            store_enabled=True,
        ),
        "changed": NodeData(
            name="CacheFrontierDataFrameNode",
            inputs={
                "df_in": NodeInputLinkValue(node_id="frontier", output_name="output"),
            },
            store_enabled=True,
        ),
    }
    task = TaskInternal(
        project_id="project-cache-frontier",
        task_id="task-cache-frontier",
        user_id="user-cache-frontier",
        pipeline=pipeline,
        target_nodes=["changed"],
        changed_node_ids=["changed"],
        graph_revision=3,
        mode=mode,
        project_settings=ProjectSettings(store_enabled=True, ttl_time=600, workers_count=4),
        project_variables=ProjectVariables(variables={}),
        license_type="000",
    )

    async def fake_restore(cls, *, node_id, expected_output_names, **_kwargs):
        if node_id != restorable_node_id:
            return None
        restored_df = dd.from_pandas(pd.DataFrame({"value": [1, 2]}), npartitions=1)
        outputs = {
            output_name: NodeOutput(
                value=(
                    restored_df if output_name == "output"
                    else True if output_name == "signal_out"
                    else False if output_name == "signal_error"
                    else {}
                )
            )
            for output_name in expected_output_names
        }
        return MetadataCacheEntry.create(
            outputs=outputs,
            metadata=dict.fromkeys(expected_output_names),
        )

    monkeypatch.setattr(
        DFOutputBaseNode,
        "restore_execution_snapshot",
        classmethod(fake_restore),
    )
    processor = PipelineProcessor(
        task=task,
        data_store=object(),
        data_index_store=object(),
        metadata_store=object(),
    )

    await processor._prepare_cache_frontier()

    assert processor.restored_nodes == [restorable_node_id]
    assert processor.effective_execution_order == expected_execution_order


@pytest.mark.asyncio
async def test_pipeline_processor_does_not_use_cache_frontier_without_dirty_state(monkeypatch) -> None:
    _register_nodes(MetadataSeedDataFrameNode)
    task = TaskInternal(
        project_id="project-clean-full-run",
        task_id="task-clean-full-run",
        user_id="user-clean-full-run",
        pipeline={
            "source": NodeData(
                name="MetadataSeedDataFrameNode",
                inputs={},
                store_enabled=True,
            ),
        },
        mode=PipelineExecutionMode.FULL,
        project_settings=ProjectSettings(store_enabled=True, ttl_time=600, workers_count=4),
        project_variables=ProjectVariables(variables={}),
        license_type="000",
    )

    async def fail_restore(*_args, **_kwargs):
        raise AssertionError("A clean FULL run must not use the cache frontier")

    monkeypatch.setattr(DFOutputBaseNode, "restore_execution_snapshot", fail_restore)
    processor = PipelineProcessor(
        task=task,
        data_store=object(),
        data_index_store=object(),
        metadata_store=object(),
    )

    await processor._prepare_cache_frontier()

    assert processor.restored_nodes == []
    assert processor.effective_execution_order == ["source"]


@pytest.mark.asyncio
async def test_pipeline_processor_supports_variable_flow_in_metadata_mode() -> None:
    _register_nodes(MetadataSeedDataFrameNode, DataFrameSelectVariables, ManageVariables)

    pipeline = {
        "seed_df": NodeData(
            name="MetadataSeedDataFrameNode",
            inputs={},
        ),
        "select_vars": NodeData(
            name="DataFrameSelectVariables",
            inputs={
                "df": NodeInputLinkValue(node_id="seed_df", output_name="output"),
                "selected_variables": NodeInputConstantValue(
                    value={
                        "ctx_value": {"source_column_name": "ctx_value", "agg_func": "first"},
                    }
                ),
            },
        ),
        "manage_vars": NodeData(
            name="ManageVariables",
            inputs={
                "input_variables": NodeInputLinkValue(node_id="select_vars", output_name="output_variables"),
                "defined_variables": NodeInputConstantValue(
                    value={
                        "ctx_copy": {
                            "type": IO.STRING,
                            "value_input": {
                                "__dvt_type": "expr",
                                "value": "ctx_value",
                                "expression_kind": "single",
                            },
                        }
                    }
                ),
            },
        ),
    }

    task = TaskInternal(
        project_id="proj-metadata-variables",
        task_id="task-metadata-variables",
        user_id="user-metadata-variables",
        pipeline=pipeline,
        target_nodes=["manage_vars"],
        mode=PipelineExecutionMode.METADATA_ONLY,
        project_settings=ProjectSettings(
            store_enabled=False,
            ttl_time=10 * 60,
            workers_count=4,
        ),
        project_variables=ProjectVariables(variables={}),
        license_type='000',
    )

    processor = PipelineProcessor(task=task)
    result = await processor.process()

    assert result.success is True
    assert processor.executed_nodes == ["seed_df", "select_vars", "manage_vars"]
    assert processor.nodes_metadata["select_vars"]["output_variables"].type == "VARIABLE_MAP"
    assert processor.nodes_metadata["manage_vars"]["output_variables"].type == "VARIABLE_MAP"
    assert isinstance(
        processor.nodes_outputs["select_vars"]["output_variables"].value["ctx_value"].value,
        UnresolvedValue,
    )
    assert isinstance(
        processor.nodes_outputs["manage_vars"]["output_variables"].value["ctx_copy"].value,
        UnresolvedValue,
    )


@pytest.mark.asyncio
async def test_pipeline_processor_runs_metadata_variable_prepass_for_db_read_nodes(monkeypatch) -> None:
    from src.node_dsl.registry import nodes as nodes_registry

    _register_nodes(CreateVariable, ManageVariables, ReadQueryFromDBV3)
    registered_read_query_class = nodes_registry.get("ReadQueryFromDBV3")

    captured_queries: list[str] = []

    def _capture_infer_metadata(self):
        captured_queries.append(self.sql_code)
        return {"output": DataFrameMetadata(columns=[])}

    monkeypatch.setattr(registered_read_query_class, "infer_metadata", _capture_infer_metadata)

    pipeline = {
        "create_var": NodeData(
            name="CreateVariable",
            inputs={
                "name": NodeInputConstantValue(value="target_table"),
                "type": NodeInputConstantValue(value=IO.STRING),
                "value": NodeInputConstantValue(value="warehouse.events"),
            },
        ),
        "manage_vars": NodeData(
            name="ManageVariables",
            inputs={
                "input_variables": NodeInputLinkValue(node_id="create_var", output_name="output_variables"),
                "defined_variables": NodeInputConstantValue(
                    value={
                        "target_table_copy": {
                            "type": IO.STRING,
                            "value_input": {
                                "__dvt_type": "expr",
                                "value": "target_table",
                                "expression_kind": "single",
                            },
                        }
                    }
                ),
            },
        ),
        "read_query": NodeData(
            name="ReadQueryFromDBV3",
            inputs={
                "connection": NodeInputConstantValue(value=sa.create_engine("sqlite:///:memory:")),
                "sql_code": NodeInputConstantValue(
                    value={
                        "__dvt_type": "expr",
                        "value": "SELECT * FROM {{ target_table_copy }}",
                        "expression_kind": "template",
                    }
                ),
                "input_variables": NodeInputLinkValue(node_id="manage_vars", output_name="output_variables"),
            },
        ),
    }

    task = TaskInternal(
        project_id="proj-db-prepass",
        task_id="task-db-prepass",
        user_id="user-db-prepass",
        pipeline=pipeline,
        target_nodes=["read_query"],
        mode=PipelineExecutionMode.METADATA_ONLY,
        project_settings=ProjectSettings(
            store_enabled=False,
            ttl_time=10 * 60,
            workers_count=4,
        ),
        project_variables=ProjectVariables(variables={}),
        license_type='000',
    )

    processor = PipelineProcessor(task=task)
    result = await processor.process()

    assert result.success is True
    assert processor.executed_nodes == ["create_var", "manage_vars", "read_query"]
    assert captured_queries == ['SELECT * FROM "warehouse"."events"']


@pytest.mark.asyncio
async def test_pipeline_processor_resolves_dataframe_filter_expression_operand_in_full_mode() -> None:
    _register_nodes(MetadataSeedDataFrameNode, ManageVariables, DataFrameFilter)

    pipeline = {
        "seed_df": NodeData(
            name="MetadataSeedDataFrameNode",
            inputs={},
        ),
        "manage_vars": NodeData(
            name="ManageVariables",
            inputs={
                "defined_variables": NodeInputConstantValue(
                    value={
                        "threshold": {
                            "type": IO.INT,
                            "value": 1,
                        }
                    }
                ),
            },
        ),
        "filter": NodeData(
            name="DataFrameFilter",
            inputs={
                "df": NodeInputLinkValue(node_id="seed_df", output_name="output"),
                "input_variables": NodeInputLinkValue(
                    node_id="manage_vars",
                    output_name="output_variables",
                ),
                "conditions": NodeInputConstantValue(
                    value={
                        "kind": "condition",
                        "left": {"type": "column", "column": "ctx_int"},
                        "operator": ">",
                        "right": {
                            "type": "expression",
                            "value": {
                                "__dvt_type": "expr",
                                "value": "threshold",
                                "expression_kind": "single",
                            },
                        },
                    }
                ),
            },
        ),
    }

    task = TaskInternal(
        project_id="proj-df-filter-expression",
        task_id="task-df-filter-expression",
        user_id="user-df-filter-expression",
        pipeline=pipeline,
        target_nodes=["filter"],
        mode=PipelineExecutionMode.FULL,
        project_settings=ProjectSettings(
            store_enabled=False,
            ttl_time=10 * 60,
            workers_count=4,
        ),
        project_variables=ProjectVariables(variables={}),
        license_type='000',
    )

    processor = PipelineProcessor(task=task)
    result = await processor.process()

    assert result.success is True
    filtered = processor.nodes_outputs["filter"]["output"].value.compute()
    assert filtered["ctx_int"].tolist() == [2]


@pytest.mark.asyncio
async def test_pipeline_processor_does_not_evaluate_dataframe_filter_expression_in_metadata_mode() -> None:
    _register_nodes(MetadataSeedDataFrameNode, DataFrameFilter)

    pipeline = {
        "seed_df": NodeData(
            name="MetadataSeedDataFrameNode",
            inputs={},
        ),
        "filter": NodeData(
            name="DataFrameFilter",
            inputs={
                "df": NodeInputLinkValue(node_id="seed_df", output_name="output"),
                "conditions": NodeInputConstantValue(
                    value={
                        "kind": "condition",
                        "left": {"type": "column", "column": "ctx_int"},
                        "operator": ">",
                        "right": {
                            "type": "expression",
                            "value": {
                                "__dvt_type": "expr",
                                "value": "missing_threshold",
                                "expression_kind": "single",
                            },
                        },
                    }
                ),
            },
        ),
    }

    task = TaskInternal(
        project_id="proj-df-filter-expression-meta",
        task_id="task-df-filter-expression-meta",
        user_id="user-df-filter-expression-meta",
        pipeline=pipeline,
        target_nodes=["filter"],
        mode=PipelineExecutionMode.METADATA_ONLY,
        project_settings=ProjectSettings(
            store_enabled=False,
            ttl_time=10 * 60,
            workers_count=4,
        ),
        project_variables=ProjectVariables(variables={}),
        license_type='000',
    )

    processor = PipelineProcessor(task=task)
    result = await processor.process()

    assert result.success is True
    assert "filter" in processor.nodes_metadata
    assert processor.nodes_metadata["filter"]["output"].columns


@pytest.mark.asyncio
async def test_pipeline_processor_skips_output_nodes_before_instantiation_in_metadata_mode(monkeypatch) -> None:
    _register_nodes(WriteDataFrameToDBV3)

    def _fail_from_pipeline_processor(cls, **_kwargs):
        raise AssertionError("WriteDataFrameToDBV3 should be skipped before instantiation in metadata mode")

    monkeypatch.setattr(
        WriteDataFrameToDBV3,
        "from_pipeline_processor",
        classmethod(_fail_from_pipeline_processor),
    )

    pipeline = {
        "write_df": NodeData(
            name="WriteDataFrameToDBV3",
            inputs={
                "table_name": NodeInputConstantValue(
                    value={
                        "__dvt_type": "expr",
                        "value": "missing_table",
                        "expression_kind": "single",
                    }
                ),
            },
        ),
    }

    task = TaskInternal(
        project_id="proj-write-skip",
        task_id="task-write-skip",
        user_id="user-write-skip",
        pipeline=pipeline,
        target_nodes=["write_df"],
        mode=PipelineExecutionMode.METADATA_ONLY,
        project_settings=ProjectSettings(
            store_enabled=False,
            ttl_time=10 * 60,
            workers_count=4,
        ),
        project_variables=ProjectVariables(variables={}),
        license_type='000',
    )

    processor = PipelineProcessor(task=task)
    result = await processor.process()

    assert result.success is True
    assert processor.executed_nodes == []
    assert processor.failed_nodes == []


@pytest.mark.asyncio
async def test_pipeline_processor_auto_activates_signal_out_for_regular_nodes() -> None:
    _register_nodes(SimpleInputNode)

    pipeline = {
        "source": NodeData(
            name="SimpleInputNode",
            inputs={"value_in": NodeInputConstantValue(value="upstream")},
        ),
        "target": NodeData(
            name="SimpleInputNode",
            inputs={
                "value_in": NodeInputConstantValue(value="downstream"),
                "signal_in": NodeInputLinkValue(node_id="source", output_name="signal_out"),
            },
        ),
    }

    task = TaskInternal(
        project_id="proj-signal-auto",
        task_id="task-signal-auto",
        user_id="user-signal-auto",
        pipeline=pipeline,
        target_nodes=["target"],
        mode=PipelineExecutionMode.FULL,
        project_settings=ProjectSettings(store_enabled=False, ttl_time=10 * 60, workers_count=4),
        project_variables=ProjectVariables(variables={}),
        license_type='000',
    )

    processor = PipelineProcessor(task=task)
    result = await processor.process()

    assert result.success is True
    assert processor.executed_nodes == ["source", "target"]
    assert processor.node_signal_states["source"]["signal_out"] is True


@pytest.mark.asyncio
async def test_pipeline_processor_routes_only_active_signal_branch() -> None:
    _register_nodes(ConditionalSignalRouter, SimpleInputNode)

    pipeline = {
        "router": NodeData(
            name="ConditionalSignalRouter",
            inputs={"condition": NodeInputConstantValue(value=True)},
        ),
        "then_node": NodeData(
            name="SimpleInputNode",
            inputs={
                "value_in": NodeInputConstantValue(value="then"),
                "signal_in": NodeInputLinkValue(node_id="router", output_name="then_signal"),
            },
        ),
        "else_node": NodeData(
            name="SimpleInputNode",
            inputs={
                "value_in": NodeInputConstantValue(value="else"),
                "signal_in": NodeInputLinkValue(node_id="router", output_name="else_signal"),
            },
        ),
    }

    task = TaskInternal(
        project_id="proj-router-active-branch",
        task_id="task-router-active-branch",
        user_id="user-router-active-branch",
        pipeline=pipeline,
        target_nodes=["then_node", "else_node"],
        mode=PipelineExecutionMode.FULL,
        project_settings=ProjectSettings(store_enabled=False, ttl_time=10 * 60, workers_count=4),
        project_variables=ProjectVariables(variables={}),
        license_type='000',
    )

    processor = PipelineProcessor(task=task)
    result = await processor.process()

    assert result.success is True
    assert processor.executed_nodes == ["router", "then_node"]
    assert processor.skipped_nodes == ["else_node"]
    assert processor.nodes_outputs["then_node"]["value_out"].value == "Processed: then"
    assert processor.node_signal_states["router"]["then_signal"] is True
    assert processor.node_signal_states["router"]["else_signal"] is False


@pytest.mark.asyncio
async def test_pipeline_processor_propagates_skip_from_inactive_signal_branch() -> None:
    _register_nodes(ConditionalSignalRouter, SimpleInputNode, SimpleOutputNode)

    pipeline = {
        "router": NodeData(
            name="ConditionalSignalRouter",
            inputs={"condition": NodeInputConstantValue(value=True)},
        ),
        "inactive_branch": NodeData(
            name="SimpleInputNode",
            inputs={
                "value_in": NodeInputConstantValue(value="else"),
                "signal_in": NodeInputLinkValue(node_id="router", output_name="else_signal"),
            },
        ),
        "inactive_final": NodeData(
            name="SimpleOutputNode",
            inputs={"value_final": NodeInputLinkValue(node_id="inactive_branch", output_name="value_out")},
        ),
    }

    task = TaskInternal(
        project_id="proj-router-skip-propagation",
        task_id="task-router-skip-propagation",
        user_id="user-router-skip-propagation",
        pipeline=pipeline,
        target_nodes=["inactive_final"],
        mode=PipelineExecutionMode.FULL,
        project_settings=ProjectSettings(store_enabled=False, ttl_time=10 * 60, workers_count=4),
        project_variables=ProjectVariables(variables={}),
        license_type='000',
    )

    processor = PipelineProcessor(task=task)
    result = await processor.process()

    assert result.success is True
    assert processor.executed_nodes == ["router"]
    assert processor.skipped_nodes == ["inactive_branch", "inactive_final"]


@pytest.mark.asyncio
async def test_pipeline_processor_requires_all_incoming_signals_to_be_active() -> None:
    _register_nodes(ConditionalSignalRouter, SimpleInputNode)

    pipeline = {
        "source": NodeData(
            name="SimpleInputNode",
            inputs={"value_in": NodeInputConstantValue(value="source")},
        ),
        "router": NodeData(
            name="ConditionalSignalRouter",
            inputs={"condition": NodeInputConstantValue(value=True)},
        ),
        "join_node": NodeData(
            name="SimpleInputNode",
            inputs={
                "value_in": NodeInputConstantValue(value="joined"),
                "signal_in": [
                    NodeInputLinkValue(node_id="source", output_name="signal_out"),
                    NodeInputLinkValue(node_id="router", output_name="else_signal"),
                ],
            },
        ),
    }

    task = TaskInternal(
        project_id="proj-router-and-signal",
        task_id="task-router-and-signal",
        user_id="user-router-and-signal",
        pipeline=pipeline,
        target_nodes=["join_node"],
        mode=PipelineExecutionMode.FULL,
        project_settings=ProjectSettings(store_enabled=False, ttl_time=10 * 60, workers_count=4),
        project_variables=ProjectVariables(variables={}),
        license_type='000',
    )

    processor = PipelineProcessor(task=task)
    result = await processor.process()

    assert result.success is True
    assert processor.executed_nodes == ["source", "router"]
    assert processor.skipped_nodes == ["join_node"]


@pytest.mark.asyncio
async def test_pipeline_processor_keeps_both_router_branches_reachable_in_metadata_mode() -> None:
    _register_nodes(ConditionalSignalRouter, SimpleInputNode)

    pipeline = {
        "router": NodeData(
            name="ConditionalSignalRouter",
            inputs={"condition": NodeInputConstantValue(value=False)},
        ),
        "then_node": NodeData(
            name="SimpleInputNode",
            inputs={
                "value_in": NodeInputConstantValue(value="then"),
                "signal_in": NodeInputLinkValue(node_id="router", output_name="then_signal"),
            },
        ),
        "else_node": NodeData(
            name="SimpleInputNode",
            inputs={
                "value_in": NodeInputConstantValue(value="else"),
                "signal_in": NodeInputLinkValue(node_id="router", output_name="else_signal"),
            },
        ),
    }

    task = TaskInternal(
        project_id="proj-router-meta",
        task_id="task-router-meta",
        user_id="user-router-meta",
        pipeline=pipeline,
        target_nodes=["then_node", "else_node"],
        mode=PipelineExecutionMode.METADATA_ONLY,
        project_settings=ProjectSettings(store_enabled=False, ttl_time=10 * 60, workers_count=4),
        project_variables=ProjectVariables(variables={}),
        license_type='000',
    )

    processor = PipelineProcessor(task=task)
    result = await processor.process()

    assert result.success is True
    assert processor.executed_nodes[0] == "router"
    assert set(processor.executed_nodes[1:]) == {"then_node", "else_node"}
    assert processor.skipped_nodes == []


def build_simple_pipeline():
    from src.nodes.testing.simple_input import SimpleInputNode
    from src.nodes.testing.simple_output import SimpleOutputNode

    _register_nodes(SimpleInputNode, SimpleOutputNode)

    return {
        "simple_input": NodeData(
            name="SimpleInputNode",
            inputs={"value_in": NodeInputConstantValue(value="hello")},
        ),
        "simple_output": NodeData(
            name="SimpleOutputNode",
            inputs={"value_final": NodeInputLinkValue(node_id="simple_input", output_name="value_out")},
        ),
    }


@pytest.mark.asyncio
async def test_pipeline_processor_executes_nodes_and_collects_outputs():
    pipeline = build_simple_pipeline()
    task = TaskInternal(
        project_id="proj-1",
        task_id="task-1",
        user_id="user-1",
        pipeline=pipeline,
        target_nodes=["simple_output"],
        mode=PipelineExecutionMode.FULL,
        project_settings=ProjectSettings(
            store_enabled=False,
            ttl_time=10 * 60,
            workers_count=4
        ),
        project_variables=ProjectVariables(
            variables={"test": 1}
        ),
        license_type='000'
    )

    node_success_calls: list[str] = []
    task_succeeded = asyncio.Event()

    async def on_node_success(**kwargs):
        node_success_calls.append(kwargs["node"].node_id)

    async def on_task_success(**kwargs):
        task_succeeded.set()

    processor = PipelineProcessor(
        task=task,
        on_node_process_success=on_node_success,
        on_task_success=on_task_success,
    )

    await processor.process()

    assert task_succeeded.is_set()
    assert processor.executed_nodes == ["simple_input", "simple_output"]
    assert node_success_calls[-1] == "simple_output"

    simple_input_outputs = processor.nodes_outputs["simple_input"]["value_out"].value
    assert simple_input_outputs == "Processed: hello"


@pytest.mark.asyncio
async def test_pipeline_processor_uses_async_metadata_resolution():
    _register_nodes(AsyncMetadataNode)
    AsyncMetadataNode.infer_metadata_calls = 0

    class StaticMetadataStore:
        def __init__(self):
            self.put_calls = []

        async def get(self, _key):
            return None

        async def put(self, key, obj, ttl_lifetime):
            self.put_calls.append((key, obj, ttl_lifetime))

    class NoOpMetadataIndexStore:
        async def put(self, index_key, value, ttl):
            return None

    pipeline = {
        "async_metadata": NodeData(
            name="AsyncMetadataNode",
            inputs={},
        ),
    }
    task = TaskInternal(
        project_id="proj-async-meta",
        task_id="task-async-meta",
        user_id="user-async-meta",
        pipeline=pipeline,
        target_nodes=["async_metadata"],
        mode=PipelineExecutionMode.FULL,
        project_settings=ProjectSettings(
            store_enabled=False,
            ttl_time=10 * 60,
            workers_count=4
        ),
        project_variables=ProjectVariables(
            variables={}
        ),
        license_type='000'
    )

    metadata_calls = []
    metadata_store = StaticMetadataStore()

    async def on_node_metadata(**kwargs):
        metadata_calls.append(kwargs["metadata"])

    processor = PipelineProcessor(
        task=task,
        on_node_metadata=on_node_metadata,
        metadata_store=metadata_store,
        metadata_index_store=NoOpMetadataIndexStore(),
    )

    result = await processor.process()

    assert result.success is True
    assert metadata_calls == [{"output": {"kind": "async-metadata"}}]
    assert processor.nodes_metadata["async_metadata"] == {"output": {"kind": "async-metadata"}}
    assert AsyncMetadataNode.infer_metadata_calls == 1
    assert len(metadata_store.put_calls) == 1
    assert metadata_store.put_calls[0][1].metadata == {"output": {"kind": "async-metadata"}}


@pytest.mark.asyncio
async def test_pipeline_processor_executes_only_target_subgraph_in_full_mode():
    from src.nodes.testing.simple_input import SimpleInputNode
    from src.nodes.testing.simple_output import SimpleOutputNode

    _register_nodes(SimpleInputNode, SimpleOutputNode)

    pipeline = {
        "simple_input": NodeData(
            name="SimpleInputNode",
            inputs={"value_in": NodeInputConstantValue(value="hello")},
        ),
        "simple_output": NodeData(
            name="SimpleOutputNode",
            inputs={"value_final": NodeInputLinkValue(node_id="simple_input", output_name="value_out")},
        ),
        "extra_input": NodeData(
            name="SimpleInputNode",
            inputs={"value_in": NodeInputConstantValue(value="secondary")},
        ),
        "extra_output": NodeData(
            name="SimpleOutputNode",
            inputs={"value_final": NodeInputLinkValue(node_id="extra_input", output_name="value_out")},
        ),
        "future_output": NodeData(
            name="SimpleOutputNode",
            inputs={},
        ),
    }

    task = TaskInternal(
        project_id="proj-disconnected",
        task_id="task-disconnected",
        user_id="user-disconnected",
        pipeline=pipeline,
        target_nodes=["simple_output"],
        mode=PipelineExecutionMode.FULL,
        project_settings=ProjectSettings(
            store_enabled=False,
            ttl_time=10 * 60,
            workers_count=4
        ),
        project_variables=ProjectVariables(
            variables={"test": 1}
        ),
        license_type='000'
    )

    processor = PipelineProcessor(task=task)

    result = await processor.process()

    assert result.success is True
    assert processor.execution_order == ["simple_input", "simple_output"]
    assert processor.executed_nodes == ["simple_input", "simple_output"]
    assert "extra_input" not in processor.executed_nodes
    assert "extra_output" not in processor.executed_nodes
    assert "future_output" not in processor.failed_nodes
    assert "future_output" not in processor.skipped_nodes


@pytest.mark.asyncio
async def test_pipeline_processor_executes_only_target_subgraph_in_metadata_mode():
    from src.nodes.testing.simple_input import SimpleInputNode
    from src.nodes.testing.simple_output import SimpleOutputNode

    _register_nodes(SimpleInputNode, SimpleOutputNode)

    pipeline = {
        "simple_input": NodeData(
            name="SimpleInputNode",
            inputs={"value_in": NodeInputConstantValue(value="hello")},
        ),
        "simple_output": NodeData(
            name="SimpleOutputNode",
            inputs={"value_final": NodeInputLinkValue(node_id="simple_input", output_name="value_out")},
        ),
        "extra_input": NodeData(
            name="SimpleInputNode",
            inputs={"value_in": NodeInputConstantValue(value="secondary")},
        ),
        "extra_output": NodeData(
            name="SimpleOutputNode",
            inputs={"value_final": NodeInputLinkValue(node_id="extra_input", output_name="value_out")},
        ),
    }

    task = TaskInternal(
        project_id="proj-metadata",
        task_id="task-metadata",
        user_id="user-metadata",
        pipeline=pipeline,
        target_nodes=["simple_output"],
        mode=PipelineExecutionMode.METADATA_ONLY,
        project_settings=ProjectSettings(
            store_enabled=False,
            ttl_time=10 * 60,
            workers_count=4
        ),
        project_variables=ProjectVariables(
            variables={"test": 1}
        ),
        license_type='000'
    )

    processor = PipelineProcessor(task=task)

    result = await processor.process()

    assert result.success is True
    assert processor.execution_order == ["simple_input", "simple_output"]
    assert processor.executed_nodes == ["simple_input"]
    assert "extra_input" not in processor.executed_nodes
    assert "extra_output" not in processor.executed_nodes


@pytest.mark.asyncio
async def test_pipeline_processor_resolves_project_variable_constant_inputs():
    from src.nodes.testing.simple_input import SimpleInputNode

    _register_nodes(SimpleInputNode)

    pipeline = {
        "simple_input": NodeData(
            name="SimpleInputNode",
            inputs={
                "value_in": NodeInputConstantValue(
                    value={"__dvt_type": "expr", "value": "input_message", "expression_kind": "single"},
                )
            },
        ),
    }

    task = TaskInternal(
        project_id="proj-var",
        task_id="task-var",
        user_id="user-var",
        pipeline=pipeline,
        target_nodes=["simple_input"],
        mode=PipelineExecutionMode.FULL,
        project_settings=ProjectSettings(
            store_enabled=False,
            ttl_time=10 * 60,
            workers_count=4
        ),
        project_variables=ProjectVariables(
            variables={"input_message": "hello-from-variable"}
        ),
        license_type='000'
    )

    processor = PipelineProcessor(task=task)
    result = await processor.process()

    assert result.success is True
    assert processor.nodes_outputs["simple_input"]["value_out"].value == "Processed: hello-from-variable"


@pytest.mark.asyncio
async def test_pipeline_processor_resolves_constant_variable_from_linked_create_variable_nodes():
    from src.node_dsl.node_typing import IO
    from src.nodes.primitive.create_variable import CreateVariable
    from src.nodes.testing.simple_input import SimpleInputNode

    _register_nodes(CreateVariable, SimpleInputNode)

    pipeline = {
        "create_var_1": NodeData(
            name="CreateVariable",
            inputs={
                "name": NodeInputConstantValue(value="msg"),
                "type": NodeInputConstantValue(value=IO.STRING),
                "value": NodeInputConstantValue(value="from_link_1"),
            },
        ),
        "create_var_2": NodeData(
            name="CreateVariable",
            inputs={
                "name": NodeInputConstantValue(value="other"),
                "type": NodeInputConstantValue(value=IO.STRING),
                "value": NodeInputConstantValue(value="from_link_2"),
            },
        ),
        "consumer": NodeData(
            name="SimpleInputNode",
            inputs={
                "value_in": NodeInputConstantValue(
                    value={"__dvt_type": "expr", "value": "msg", "expression_kind": "single"}
                ),
                "input_variables": [
                    NodeInputLinkValue(node_id="create_var_1", output_name="output_variables"),
                    NodeInputLinkValue(node_id="create_var_2", output_name="output_variables"),
                ],
            },
        ),
    }

    task = TaskInternal(
        project_id="proj-linked-var",
        task_id="task-linked-var",
        user_id="user-linked-var",
        pipeline=pipeline,
        target_nodes=["consumer"],
        mode=PipelineExecutionMode.FULL,
        project_settings=ProjectSettings(
            store_enabled=False,
            ttl_time=10 * 60,
            workers_count=4,
        ),
        project_variables=ProjectVariables(
            variables={"msg": "from_project_var"},
        ),
        license_type='000'
    )

    processor = PipelineProcessor(task=task)
    result = await processor.process()

    assert result.success is True
    assert processor.nodes_outputs["consumer"]["value_out"].value == "Processed: from_link_1"


@pytest.mark.asyncio
async def test_pipeline_processor_ignores_empty_linked_output_variables():
    from src.nodes.testing.simple_input import SimpleInputNode

    _register_nodes(SimpleInputNode)

    pipeline = {
        "producer": NodeData(
            name="SimpleInputNode",
            inputs={"value_in": NodeInputConstantValue(value="upstream")},
        ),
        "consumer": NodeData(
            name="SimpleInputNode",
            inputs={
                "value_in": NodeInputConstantValue(
                    value={"__dvt_type": "expr", "value": "msg", "expression_kind": "single"}
                ),
                "input_variables": NodeInputLinkValue(
                    node_id="producer",
                    output_name="output_variables",
                ),
            },
        ),
    }

    task = TaskInternal(
        project_id="proj-empty-linked-vars",
        task_id="task-empty-linked-vars",
        user_id="user-empty-linked-vars",
        pipeline=pipeline,
        target_nodes=["consumer"],
        mode=PipelineExecutionMode.FULL,
        project_settings=ProjectSettings(
            store_enabled=False,
            ttl_time=10 * 60,
            workers_count=4,
        ),
        project_variables=ProjectVariables(
            variables={"msg": "from_project_var"},
        ),
    )

    processor = PipelineProcessor(task=task)
    result = await processor.process()

    assert result.success is True
    assert processor.nodes_outputs["consumer"]["value_out"].value == "Processed: from_project_var"


@pytest.mark.asyncio
async def test_pipeline_processor_handles_validation_errors():
    from src.nodes.testing.simple_output import SimpleOutputNode
    from src.nodes.testing.validation_error_node import ValidationErrorNode

    _register_nodes(ValidationErrorNode, SimpleOutputNode)

    pipeline = {
        "validation": NodeData(
            name="ValidationErrorNode",
            inputs={"value_in": NodeInputConstantValue(value="boom")},
        ),
        "final": NodeData(
            name="SimpleOutputNode",
            inputs={"value_final": NodeInputLinkValue(node_id="validation", output_name="value_out")},
        ),
    }

    task = TaskInternal(
        project_id="proj-err",
        task_id="task-err",
        user_id="user-err",
        pipeline=pipeline,
        target_nodes=["final"],
        mode=PipelineExecutionMode.FULL,
        project_settings=ProjectSettings(
            store_enabled=False,
            ttl_time=10 * 60,
            workers_count=4
        ),
        project_variables=ProjectVariables(
            variables={'test': 1}
        ),
        license_type='000'
    )

    processor = PipelineProcessor(
        task=task,
    )

    result = await processor.process()

    assert result.success is False
    assert processor.executed_nodes == []
    assert processor.failed_nodes == ["validation"]


@pytest.mark.asyncio
async def test_pipeline_processor_tracks_runtime_errors():
    from src.nodes.testing.error_node import ErrorNode
    from src.nodes.testing.simple_output import SimpleOutputNode

    _register_nodes(ErrorNode, SimpleOutputNode)

    pipeline = {
        "runtime_error": NodeData(
            name="ErrorNode",
            inputs={"value_in": NodeInputConstantValue(value="boom")},
        ),
        "final": NodeData(
            name="SimpleOutputNode",
            inputs={"value_final": NodeInputLinkValue(node_id="runtime_error", output_name="value_out")},
        ),
    }

    task = TaskInternal(
        project_id="proj-runtime-err",
        task_id="task-runtime-err",
        user_id="user-runtime-err",
        pipeline=pipeline,
        target_nodes=["final"],
        mode=PipelineExecutionMode.FULL,
        project_settings=ProjectSettings(
            store_enabled=False,
            ttl_time=10 * 60,
            workers_count=4,
        ),
        project_variables=ProjectVariables(variables={"test": 1}),
        license_type='000'
    )

    processor = PipelineProcessor(task=task)
    result = await processor.process()

    assert result.success is False
    assert processor.failed_nodes == ["runtime_error"]


@pytest.mark.asyncio
async def test_pipeline_processor_routes_runtime_error_to_signal_error_branch():
    from src.nodes.testing.error_node import ErrorNode
    from src.nodes.testing.simple_input import SimpleInputNode

    _register_nodes(ErrorNode, SimpleInputNode)

    pipeline = {
        "runtime_error": NodeData(
            name="ErrorNode",
            inputs={"value_in": NodeInputConstantValue(value="boom")},
        ),
        "handler": NodeData(
            name="SimpleInputNode",
            inputs={
                "signal_in": NodeInputLinkValue(node_id="runtime_error", output_name="signal_error"),
                "input_variables": NodeInputLinkValue(node_id="runtime_error", output_name="output_variables"),
                "value_in": NodeInputConstantValue(
                    value={
                        "__dvt_type": "expr",
                        "value": "input_variables.__dvt_error_text",
                        "expression_kind": "single",
                    }
                ),
            },
        ),
    }

    task = TaskInternal(
        project_id="proj-runtime-error-branch",
        task_id="task-runtime-error-branch",
        user_id="user-runtime-error-branch",
        pipeline=pipeline,
        target_nodes=["handler"],
        mode=PipelineExecutionMode.FULL,
        project_settings=ProjectSettings(
            store_enabled=False,
            ttl_time=10 * 60,
            workers_count=4,
        ),
        project_variables=ProjectVariables(variables={}),
        license_type='000',
    )

    node_error_messages: list[str] = []
    task_error_messages: list[str] = []
    task_error_execution_snapshots: list[list[str]] = []
    processor: PipelineProcessor | None = None

    async def on_node_error(**kwargs):
        node_error_messages.append(kwargs["message"])

    async def on_task_error(**kwargs):
        task_error_messages.append(kwargs["message"])
        assert processor is not None
        task_error_execution_snapshots.append(list(processor.executed_nodes))

    processor = PipelineProcessor(
        task=task,
        on_node_error=on_node_error,
        on_task_error=on_task_error,
    )
    result = await processor.process()

    assert result.success is False
    assert processor.failed_nodes == ["runtime_error"]
    assert processor.executed_nodes == ["handler"]
    assert node_error_messages == ["Error in ErrorNode"]
    assert task_error_messages == ["Error in ErrorNode"]
    assert task_error_execution_snapshots == [["handler"]]
    assert processor.nodes_outputs["runtime_error"]["signal_out"].value is False
    assert processor.nodes_outputs["runtime_error"]["signal_error"].value is True
    error_output_variables = processor.nodes_outputs["runtime_error"]["output_variables"].value
    assert error_output_variables["__dvt_error_text"].value == "Error in ErrorNode"
    assert processor.nodes_outputs["handler"]["value_out"].value == "Processed: Error in ErrorNode"


@pytest.mark.asyncio
async def test_pipeline_processor_reports_unsafe_expression_as_node_input_error():
    _register_nodes(SimpleInputNode)

    pipeline = {
        "unsafe_input": NodeData(
            name="SimpleInputNode",
            inputs={
                "value_in": NodeInputConstantValue(
                    value={
                        "__dvt_type": "expr",
                        "value": "input_variables.__private_value",
                        "expression_kind": "single",
                    }
                ),
            },
        ),
    }
    task = TaskInternal(
        project_id="proj-unsafe-expression",
        task_id="task-unsafe-expression",
        user_id="user-unsafe-expression",
        pipeline=pipeline,
        target_nodes=["unsafe_input"],
        mode=PipelineExecutionMode.FULL,
        project_settings=ProjectSettings(
            store_enabled=False,
            ttl_time=10 * 60,
            workers_count=4,
        ),
        project_variables=ProjectVariables(
            variables={"__private_value": "secret"},
        ),
        license_type="000",
    )
    task_error_messages: list[str] = []

    async def on_task_error(**kwargs):
        task_error_messages.append(kwargs["message"])

    result = await PipelineProcessor(
        task=task,
        on_task_error=on_task_error,
    ).process()

    assert result.success is False
    assert result.error_message is not None
    assert result.error_message.startswith("Node unsafe_input: Unsafe expression access:")
    assert "Unexpected error" not in result.error_message
    assert task_error_messages == [result.error_message]


@pytest.mark.asyncio
async def test_pipeline_processor_propagates_skips_after_validation_error():
    """
    Regression: если нода A падает на validate(), то нода B, зависящая от A, пропускается.
    Но также должны пропускаться и все последующие ноды, зависящие от B; иначе build_node_kwargs
    упадет с NodeInputError из-за отсутствующих outputs от пропущенной ноды.
    """
    from src.nodes.testing.simple_input import SimpleInputNode
    from src.nodes.testing.simple_output import SimpleOutputNode
    from src.nodes.testing.validation_error_node import ValidationErrorNode

    _register_nodes(ValidationErrorNode, SimpleInputNode, SimpleOutputNode)

    pipeline = {
        "validation": NodeData(
            name="ValidationErrorNode",
            inputs={"value_in": NodeInputConstantValue(value="boom")},
        ),
        "middle": NodeData(
            name="SimpleInputNode",
            inputs={"value_in": NodeInputLinkValue(node_id="validation", output_name="value_out")},
        ),
        "final": NodeData(
            name="SimpleOutputNode",
            inputs={"value_final": NodeInputLinkValue(node_id="middle", output_name="value_out")},
        ),
    }

    task = TaskInternal(
        project_id="proj-err",
        task_id="task-err",
        user_id="user-err",
        pipeline=pipeline,
        target_nodes=["final"],
        mode=PipelineExecutionMode.FULL,
        project_settings=ProjectSettings(
            store_enabled=False,
            ttl_time=10 * 60,
            workers_count=4,
        ),
        project_variables=ProjectVariables(
            variables={"test": 1},
        ),
        license_type='000'
    )

    task_failed = asyncio.Event()
    error_messages: list[str] = []

    async def on_task_error(**kwargs):
        error_messages.append(kwargs["message"])
        task_failed.set()

    processor = PipelineProcessor(
        task=task,
        on_task_error=on_task_error,
    )

    result = await processor.process()

    assert result.success is False
    assert task_failed.is_set()
    assert error_messages
    assert "Validation error" in error_messages[0]

    assert processor.executed_nodes == []
    assert processor.failed_nodes == ["validation"]
    assert processor.skipped_nodes == ["validation", "middle", "final"]


@pytest.mark.asyncio
async def test_metadata_mode_continues_independent_branch_after_runtime_error():
    from src.nodes.testing.error_node import ErrorNode
    from src.nodes.testing.simple_input import SimpleInputNode

    _register_nodes(ErrorNode, SimpleInputNode)

    pipeline = {
        "error": NodeData(
            name="ErrorNode",
            inputs={"value_in": NodeInputConstantValue(value="boom")},
        ),
        "stable": NodeData(
            name="SimpleInputNode",
            inputs={"value_in": NodeInputConstantValue(value="stable")},
        ),
        "failed_child": NodeData(
            name="SimpleInputNode",
            inputs={"value_in": NodeInputLinkValue(node_id="error", output_name="value_out")},
        ),
    }
    task = TaskInternal(
        project_id="proj-runtime-error",
        task_id="task-runtime-error",
        user_id="user-runtime-error",
        pipeline=pipeline,
        mode=PipelineExecutionMode.METADATA_ONLY,
        project_settings=ProjectSettings(
            store_enabled=False,
            ttl_time=10 * 60,
            workers_count=4,
        ),
        project_variables=ProjectVariables(variables={}),
        license_type="000",
    )

    processor = PipelineProcessor(task=task)
    result = await processor.process()

    assert result.success is False
    assert result.error_message == "Error in ErrorNode"
    assert processor.failed_nodes == ["error"]
    assert processor.skipped_nodes == ["error", "failed_child"]
    assert processor.executed_nodes == ["stable"]
    assert processor.nodes_outputs["stable"]["value_out"].value == "Processed: stable"


@pytest.mark.asyncio
async def test_pipeline_processor_reuses_upstream_metadata_cache_for_incremental_metadata_run():
    from src.node_dsl.registry import definitions as definitions_registry
    from src.node_dsl.registry import nodes as nodes_registry
    from src.nodes.testing.simple_input import SimpleInputNode
    from src.nodes.testing.simple_output import SimpleOutputNode

    _register_nodes(SimpleInputNode, SimpleOutputNode)

    class StaticMetadataStore:
        def __init__(self, entries_by_key):
            self.entries_by_key = entries_by_key

        async def get(self, key):
            return self.entries_by_key.get(key)

        async def put(self, key, obj, ttl_lifetime):
            self.entries_by_key[key] = obj

    class NoOpMetadataIndexStore:
        async def put(self, index_key, value, ttl):
            return None

    pipeline = {
        "source": NodeData(
            name="SimpleInputNode",
            inputs={"value_in": NodeInputConstantValue(value="hello")},
        ),
        "changed": NodeData(
            name="SimpleInputNode",
            inputs={"value_in": NodeInputLinkValue(node_id="source", output_name="value_out")},
        ),
        "final": NodeData(
            name="SimpleOutputNode",
            inputs={"value_final": NodeInputLinkValue(node_id="changed", output_name="value_out")},
        ),
    }

    simple_input_class = nodes_registry.get("SimpleInputNode")
    source_cache_key = create_node_inputs_fingerprint(
        node_class=simple_input_class,
        parent_hashes={},
        constant_inputs={"value_in": "hello"},
    )

    source_output_names = list(definitions_registry.get("SimpleInputNode").output_definitions.keys())
    cached_outputs = {
        "value_out": NodeOutput(value="Processed: hello"),
        "output_variables": NodeOutput(value={}),
        "signal_out": NodeOutput(value=True),
    }
    assert set(cached_outputs.keys()).issubset(set(source_output_names))
    assert "signal_error" in source_output_names

    task = TaskInternal(
        project_id="proj-incremental-meta",
        task_id="task-incremental-meta",
        user_id="user-incremental-meta",
        pipeline=pipeline,
        metadata_changed_node_ids=["changed"],
        mode=PipelineExecutionMode.METADATA_ONLY,
        project_settings=ProjectSettings(
            store_enabled=False,
            ttl_time=10 * 60,
            workers_count=4,
        ),
        project_variables=ProjectVariables(variables={}),
        license_type='000'
    )

    metadata_events = {}

    async def on_node_metadata(**kwargs):
        metadata_events[kwargs["node"].node_id] = kwargs["metadata"]

    processor = PipelineProcessor(
        task=task,
        on_node_metadata=on_node_metadata,
        metadata_store=StaticMetadataStore(
            {
                source_cache_key: MetadataCacheEntry(
                    outputs=cached_outputs,
                    metadata={"value_out": None},
                )
            }
        ),
        metadata_index_store=NoOpMetadataIndexStore(),
    )

    result = await processor.process()

    assert result.success is True
    assert processor.executed_nodes == ["changed"]
    assert processor.nodes_outputs["source"]["value_out"].value == "Processed: hello"
    assert "source" not in processor.failed_nodes
    assert metadata_events["source"] == processor.nodes_metadata["source"]


@pytest.mark.asyncio
async def test_restore_meta_cache_accepts_legacy_metadata_without_signal_outputs():
    from src.nodes.testing.simple_input import SimpleInputNode
    from src.node_dsl.registry import definitions as definitions_registry

    _register_nodes(SimpleInputNode)

    class StaticMetadataStore:
        def __init__(self, entry):
            self.entry = entry

        async def get(self, _key):
            return self.entry

    node_def = definitions_registry.get("SimpleInputNode")
    output_names = list(node_def.output_definitions.keys())
    assert "value_out" in output_names
    assert "output_variables" in output_names
    assert "signal_out" in output_names
    assert "signal_error" in output_names

    cached_outputs = {
        "value_out": NodeOutput(value="cached value"),
        "output_variables": NodeOutput(value={}),
    }
    cached_metadata = {
        "value_out": None,
    }

    task = TaskInternal(
        project_id="proj-cache",
        task_id="task-cache",
        user_id="user-cache",
        pipeline={
            "simple_input": NodeData(
                name="SimpleInputNode",
                inputs={"value_in": NodeInputConstantValue(value="hello")},
            ),
        },
        target_nodes=["simple_input"],
        mode=PipelineExecutionMode.METADATA_ONLY,
        project_settings=ProjectSettings(
            store_enabled=False,
            ttl_time=10 * 60,
            workers_count=4,
        ),
        project_variables=ProjectVariables(variables={"test": 1}),
        license_type='000'
    )

    processor = PipelineProcessor(
        task=task,
        metadata_store=StaticMetadataStore(
            MetadataCacheEntry(outputs=cached_outputs, metadata=cached_metadata)
        ),
    )

    restored = await processor._try_restore_node_meta_cache_and_skip(
        node_id="simple_input",
        current_node_name="SimpleInputNode",
        node_class=SimpleInputNode,
        meta_cache_key="cache-key",
        output_definitions=node_def.output_definitions,
    )

    assert restored is True
    assert set(processor.nodes_outputs["simple_input"].keys()) == set(output_names)
    assert set(processor.nodes_metadata["simple_input"].keys()) == set(output_names)
    assert processor.nodes_metadata["simple_input"]["value_out"] is None
    assert processor.nodes_metadata["simple_input"]["signal_out"] is None
    assert processor.nodes_metadata["simple_input"]["signal_error"] is None
    assert processor.nodes_outputs["simple_input"]["signal_out"].value is None
    assert processor.nodes_outputs["simple_input"]["signal_error"].value is None
