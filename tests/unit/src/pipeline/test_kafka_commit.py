import pytest
from tests.fixtures.kafka_commit import kafka_connection, processor, register_nodes
from tests.unit.src.modules.kafka_consumption.test_commit import make_case
from tests.unit.src.node_dsl.test_df_output_callbacks import (
    _build_data_index_store,
    _build_data_store,
)

from src.node_dsl import InputField, SignalOutputBaseNode
from src.node_dsl.core.input_values import (
    NodeInputConstantValue as Const,
    NodeInputLinkValue as Link,
)
from src.nodes.tool.commit_kafka_offsets import CommitKafkaOffsets
from src.pipeline.execution_mode import PipelineExecutionMode
from src.schemas.internal import NodeData


class CommitTestSignal(SignalOutputBaseNode):
    active: bool = InputField(default=True)
    AUTO_ACTIVATE_SIGNAL_OUTPUTS = False

    def process(self):
        self.signal_out = self.active

    def process_metadata(self):
        self.signal_out = self.active


def pipeline(signals=()):
    register_nodes(CommitKafkaOffsets, CommitTestSignal)
    data = {}
    for index, active in enumerate(signals):
        data[str(index)] = NodeData(name="CommitTestSignal", inputs={"active": Const(value=active)})
    data["commit"] = NodeData(name="CommitKafkaOffsets", store_enabled=True, inputs={
        "connection": Const(value=kafka_connection({"bootstrap_servers": ["unused:9092"]})),
        "offsets": Const(value={
            "schema_version": 1, "topic": "topic", "group_id": "group",
            "partitions": [{"partition": 0, "next_offset": 5}],
        }),
        "signal_in": ([Link(node_id=str(i), output_name="signal_out") for i in range(len(signals))]
                      if signals else Const(value=None)),
    })
    if not signals:
        del data["commit"].inputs["signal_in"]
    return data


@pytest.mark.asyncio
@pytest.mark.parametrize("signals,expected", [
    ((), True), ((True, True), True), ((True, False), False), ((False, True), False),
])
async def test_all_connected_signals_are_required(monkeypatch, signals, expected):
    _, gateway, _ = make_case()
    monkeypatch.setattr(CommitKafkaOffsets, "_gateway", lambda _: gateway)
    proc = processor(pipeline(signals))
    result = await proc.process()
    assert not proc.failed_nodes, result
    assert gateway.commit.call_count == int(expected)
    if expected:
        assert proc.node_signal_states["commit"]["signal_out"] is True
    else:
        assert "commit" in proc.skipped_nodes


@pytest.mark.asyncio
async def test_metadata_only_does_not_report_success(monkeypatch):
    monkeypatch.setattr(CommitKafkaOffsets, "_gateway", lambda _: pytest.fail("metadata connected"))
    proc = processor(pipeline(), mode=PipelineExecutionMode.METADATA_ONLY)
    result = await proc.process()
    assert not proc.failed_nodes, result
    assert "commit" not in proc.nodes_outputs
    assert proc.node_signal_states["commit"].get("signal_out", False) is False


@pytest.mark.asyncio
async def test_standalone_commit_with_cache_enabled_rechecks_positions(monkeypatch):
    _, gateway, _ = make_case()
    monkeypatch.setattr(CommitKafkaOffsets, "_gateway", lambda _: gateway)
    data = pipeline()
    store, index = _build_data_store(), _build_data_index_store()
    for iteration in range(2):
        proc = processor(data, run=str(iteration), data_store=store, data_index_store=index,
                         metadata_store=_build_data_store(), metadata_index_store=_build_data_index_store())
        result = await proc.process()
        assert not proc.failed_nodes, result
        assert proc.restored_nodes == []
        assert proc.node_signal_states["commit"]["signal_out"] is True
    assert gateway.committed.call_count == 2
    assert gateway.commit.call_count == 2


@pytest.mark.asyncio
async def test_downstream_snapshot_cannot_bypass_standalone_commit(monkeypatch):
    import dask.dataframe as dd
    import pandas as pd
    from tests.unit.src.pipeline.test_kafka_read import KafkaTestSink
    from tests.unit.src.pipeline.test_processor import CacheFrontierDataFrameNode

    _, gateway, _ = make_case()
    monkeypatch.setattr(CommitKafkaOffsets, "_gateway", lambda _: gateway)
    data = pipeline()
    register_nodes(CacheFrontierDataFrameNode, KafkaTestSink)
    data["tail"] = NodeData(name="CacheFrontierDataFrameNode", store_enabled=True, inputs={
        "df_in": Const(value=dd.from_pandas(pd.DataFrame({"value": [1]}), npartitions=1)),
        "signal_in": Link(node_id="commit", output_name="signal_out"),
    })
    data["sink"] = NodeData(name="KafkaTestSink", inputs={
        "df": Link(node_id="tail", output_name="output"),
    })
    store, index = _build_data_store(), _build_data_index_store()
    for iteration in range(2):
        proc = processor(data, run=str(iteration), targets=("sink",),
                         data_store=store, data_index_store=index)
        result = await proc.process()
        assert result.success, result
        assert not proc.restored_nodes
        saved = await CacheFrontierDataFrameNode.restore_execution_snapshot(
            project_id="kafka-commit", node_id="tail", node_name="CacheFrontierDataFrameNode",
            expected_output_names=tuple(CacheFrontierDataFrameNode.output_fields()),
            data_store=store, data_index_store=index,
        )
        assert saved is not None
    assert gateway.commit.call_count == 2


@pytest.mark.asyncio
async def test_early_variable_link_does_not_compute_reader(monkeypatch):
    from tests.fixtures.kafka_read import MemoryKafka

    from src.node_dsl.core.input_values import NodeInputExpressionValue as Expr
    from src.nodes.extract.read_kafka_messages import ReadKafkaMessages

    source = MemoryKafka()
    monkeypatch.setattr(ReadKafkaMessages, "_gateway", lambda *_: source)
    monkeypatch.setattr(CommitKafkaOffsets, "_gateway", lambda _: pytest.fail("commit connected"))
    data = pipeline()
    register_nodes(ReadKafkaMessages)
    data["read"] = NodeData(name="ReadKafkaMessages", inputs={
        "connection": data["commit"].inputs["connection"],
        "topic": Const(value="topic"), "group_id": Const(value="group"),
    })
    data["commit"].inputs.update(
        offsets=Expr(value="kafka_offsets", expression_kind="single"),
        input_variables=[Link(node_id="read", output_name="output_variables")],
    )
    proc = processor(data)
    result = await proc.process()
    assert not result.success
    assert not source.calls
