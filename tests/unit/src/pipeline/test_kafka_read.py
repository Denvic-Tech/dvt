import json

import dask.dataframe as dd
import pytest
from tests.fixtures.kafka_read import MemoryKafka
from tests.unit.src.modules.pipeline_cache.test_use_cases import _build_provider
from tests.unit.src.node_dsl.test_df_output_callbacks import (
    _build_data_index_store,
    _build_data_store,
)
from tests.unit.src.pipeline.test_processor import CacheFrontierDataFrameNode, _register_nodes

from core.hashing import get_hash

from src.modules.pipeline_cache import CodecObjectStore
from src.modules.pipeline_cache.domain.dataframe_cache import (
    ActiveDataFrameGeneration,
    dataframe_active_key,
)
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


def _patch_kafka_read(monkeypatch, gateway):
    monkeypatch.setattr(ReadKafkaMessages, "_gateway", lambda *_: gateway)

    async def validate(self):
        pass

    monkeypatch.setattr(ReadKafkaMessages, "validate", validate)
    from types import SimpleNamespace

    monkeypatch.setattr(ReadKafkaMessages, "connection", SimpleNamespace(id="connection"))


@pytest.mark.asyncio
async def test_fresh_run_bypasses_real_downstream_snapshot_and_resolves_before_signal(monkeypatch):
    _register_nodes(
        ReadKafkaMessages, CacheFrontierDataFrameNode, KafkaTestSink, KafkaTestAfterSink
    )
    gateway = MemoryKafka()
    _patch_kafka_read(monkeypatch, gateway)

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


@pytest.mark.asyncio
async def test_fresh_kafka_read_persists_new_viewer_generation_without_becoming_restorable(
    monkeypatch,
):
    _register_nodes(ReadKafkaMessages, KafkaTestSink, KafkaTestAfterSink)
    gateway = MemoryKafka()
    _patch_kafka_read(monkeypatch, gateway)

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
        "sink": NodeData(
            name="KafkaTestSink",
            inputs={"df": NodeInputLinkValue(node_id="read", output_name="output")},
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

    provider = _build_provider()
    facade = provider.create_facade()
    store = CodecObjectStore(provider.data_blob_store, provider.data_codec)
    index = provider.data_index_store
    read_ids = []
    generation_ids = []

    for iteration in range(2):
        task = TaskInternal(
            project_id="kafka-viewer-cache",
            task_id=f"viewer-run-{iteration}",
            user_id="u",
            pipeline=pipeline,
            target_nodes=["after"],
            graph_revision=iteration + 1,
            changed_node_ids=[],
            mode=PipelineExecutionMode.FULL,
            project_settings=ProjectSettings(store_enabled=True, ttl_time=600, workers_count=2),
            project_variables=ProjectVariables(variables={}),
            license_type="000",
        )
        processor = PipelineProcessor(
            task=task,
            data_store=store,
            data_index_store=index,
        )

        result = await processor.process()

        assert result.success
        assert processor.restored_nodes == []
        read_ids.append(KafkaTestAfterSink.observed["read_id"])

        preview = await facade.get_dataframe_entry(
            project_id="kafka-viewer-cache",
            node_id="read",
            output_name="output",
        )
        assert preview.total_rows == 9
        assert len(preview.dataframe) == 9

        active_payload = await provider.data_blob_store.get(
            dataframe_active_key(project_id="kafka-viewer-cache", node_id="read")
        )
        assert active_payload is not None
        active = provider.decode_data(active_payload)
        assert isinstance(active, ActiveDataFrameGeneration)
        generation_ids.append(active.generation_id)

        assert await ReadKafkaMessages.restore_execution_snapshot(
            project_id="kafka-viewer-cache",
            node_id="read",
            node_name="ReadKafkaMessages",
            expected_output_names=tuple(ReadKafkaMessages.output_fields()),
            data_store=store,
            data_index_store=index,
        ) is None

    assert read_ids[0] != read_ids[1]
    assert generation_ids[0] != generation_ids[1]
