import json

import dask.dataframe as dd
import pytest
from tests.fixtures.kafka_read import MemoryKafka
from tests.unit.src.node_dsl.test_df_output_callbacks import (
    _build_data_index_store,
    _build_data_store,
)
from tests.unit.src.pipeline.test_processor import CacheFrontierDataFrameNode, _register_nodes

from core.hashing import get_hash

from src.node_dsl import InputField, SignalOutputBaseNode
from src.node_dsl.core.input_values import NodeInputConstantValue, NodeInputLinkValue
from src.node_dsl.variables import UnresolvedValue
from src.nodes.extract.read_kafka_messages import ReadKafkaMessages
from src.pipeline.execution_mode import PipelineExecutionMode
from src.pipeline.processor import PipelineProcessor
from src.schemas.internal import NodeData, ProjectSettings, ProjectVariables, TaskInternal


class KafkaTestSink(SignalOutputBaseNode):
    df: dd.DataFrame = InputField()
    rows = None

    def process(self):
        type(self).rows = self.df.compute(scheduler="threads")


class KafkaTestAfterSink(SignalOutputBaseNode):
    observed = None

    def process(self):
        value = self.input_variables["kafka_offsets"].value
        assert not isinstance(value, UnresolvedValue)
        type(self).observed = json.loads(json.dumps(value))


@pytest.mark.asyncio
async def test_fresh_run_bypasses_real_downstream_snapshot_and_resolves_before_signal(monkeypatch):
    _register_nodes(
        ReadKafkaMessages, CacheFrontierDataFrameNode, KafkaTestSink, KafkaTestAfterSink
    )
    gateway = MemoryKafka()
    monkeypatch.setattr(ReadKafkaMessages, "_gateway", lambda *_: gateway)

    # Input validation of a real ConnectionRecord is covered by connection-node tests.
    async def validate(self):
        pass

    monkeypatch.setattr(ReadKafkaMessages, "validate", validate)
    from types import SimpleNamespace

    monkeypatch.setattr(ReadKafkaMessages, "connection", SimpleNamespace(id="connection"))

    pipeline = {
        "read": NodeData(
            name="ReadKafkaMessages",
            inputs={
                "topic": NodeInputConstantValue(value="topic"),
                "group_id": NodeInputConstantValue(value="group"),
                "rows_per_partition": NodeInputConstantValue(value=2),
            },
            store_enabled=True,
        ),
        "frontier": NodeData(
            name="CacheFrontierDataFrameNode",
            inputs={
                "df_in": NodeInputLinkValue(node_id="read", output_name="output"),
            },
            store_enabled=True,
        ),
        "sink": NodeData(
            name="KafkaTestSink",
            inputs={
                "df": NodeInputLinkValue(node_id="frontier", output_name="output"),
            },
        ),
        "after": NodeData(
            name="KafkaTestAfterSink",
            inputs={
                "input_variables": [
                    NodeInputLinkValue(node_id="read", output_name="output_variables")
                ],
                "signal_in": [NodeInputLinkValue(node_id="sink", output_name="signal_out")],
            },
        ),
    }
    store, index = _build_data_store(), _build_data_index_store()
    ids = []
    for iteration in range(2):
        events = []
        task = TaskInternal(
            project_id="kafka-cache",
            task_id=f"run-{iteration}",
            user_id="u",
            pipeline=pipeline,
            target_nodes=["after"],
            graph_revision=iteration + 1,
            changed_node_ids=["sink"] if iteration else [],
            mode=PipelineExecutionMode.FULL,
            project_settings=ProjectSettings(store_enabled=True, ttl_time=600, workers_count=2),
            project_variables=ProjectVariables(variables={}),
            license_type="000",
        )
        processor = PipelineProcessor(
            task=task,
            data_store=store,
            data_index_store=index,
            on_node_metadata=lambda events=events, **kw: events.append(
                (kw["node"].node_id, kw["metadata"])
            ),
        )
        result = await processor.process()
        assert not processor.failed_nodes, result
        assert processor.restored_nodes == []
        assert len(KafkaTestSink.rows) == 9
        assert KafkaTestAfterSink.observed["messages_read"] == 9
        ids.append(KafkaTestAfterSink.observed["read_id"])
        output = processor.nodes_outputs["read"]["output_variables"].value
        assert processor.nodes_output_hashes["read"]["output_variables"] == get_hash(output)
        descriptors = processor.nodes_metadata["read"]["output_variables"].variables
        assert all(v.value_state == "resolved" for v in descriptors)
        assert any(
            name == "read"
            and all(v.value_state == "resolved" for v in metadata["output_variables"].variables)
            for name, metadata in events
        )
        # The intermediate node really did save a restorable snapshot.
        entry = await CacheFrontierDataFrameNode.restore_execution_snapshot(
            project_id="kafka-cache",
            node_id="frontier",
            node_name="CacheFrontierDataFrameNode",
            expected_output_names=tuple(CacheFrontierDataFrameNode.output_fields()),
            data_store=store,
            data_index_store=index,
        )
        assert entry is not None
    assert ids[0] != ids[1]
