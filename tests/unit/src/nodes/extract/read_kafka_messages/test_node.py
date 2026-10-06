from dataclasses import replace
from types import SimpleNamespace

import dask
import pandas as pd
import pytest
from tests.fixtures.kafka_read import MemoryKafka

from src.modules.kafka_consumption.domain.exceptions import KafkaMessageTooLargeError
from src.modules.kafka_consumption.infra.exceptions import KafkaDecodeError
from src.modules.pipeline_cache import CodecObjectStore, DumpEngineCodec, InMemoryBlobStore
from src.modules.pipeline_cache.domain.dataframe_cache import (
    CacheGenerationState,
    dataframe_manifest_key,
)
from src.node_dsl.exceptions import NodeExecutionCancelled
from src.node_dsl.variables import UnresolvedValue
from src.nodes.extract.read_kafka_messages import ReadKafkaMessages
from src.pipeline.execution_mode import PipelineExecutionMode


def node(gateway=None, **kwargs):
    gateway = gateway or MemoryKafka()
    instance = ReadKafkaMessages(
        user_id="u",
        project_id="p",
        task_id="t",
        node_id="n",
        topic="topic",
        group_id="group",
        connection=SimpleNamespace(id="connection"),
        rows_per_partition=2,
        **kwargs,
    )
    instance._gateway = lambda _: gateway
    return instance, gateway


@pytest.mark.parametrize("scheduler", ["sync", "threads"])
def test_lazy_partial_full_replay_and_branch(scheduler):
    n, gateway = node()
    n.process()
    variables = n.output_variables
    offsets = variables["kafka_offsets"]
    assert not gateway.calls
    assert isinstance(offsets.value, UnresolvedValue)
    assert len(n.output.head(1)) == 1
    assert isinstance(offsets.value, UnresolvedValue)
    assert len(n.output.partitions[-1].compute(scheduler=scheduler)) == 0
    assert isinstance(offsets.value, UnresolvedValue)
    result = n.output.compute(scheduler=scheduler)
    assert len(result) == 9
    assert all(isinstance(dtype, pd.ArrowDtype) for dtype in result.dtypes)
    assert variables is n.output_variables and variables["kafka_offsets"] is offsets
    assert offsets.value["messages_read"] == 9
    assert n.infer_metadata()["output_variables"].variables[-4].value_state == "resolved"
    original = offsets.value.copy()
    left, right = dask.compute(n.output[["offset"]], n.output[["value"]], scheduler=scheduler)
    assert len(left) == len(right) == 9
    assert offsets.value == original
    assert n._reader.slots == len(n._reader.receipts)
    assert all(not hasattr(value, "messages") for value in n._reader.receipts.values())


def test_metadata_does_not_connect_or_read():
    n, gateway = node()
    n._gateway = lambda _: pytest.fail("metadata must not connect")
    n.process_metadata()
    assert len(n.output.compute()) == 0
    assert not gateway.calls
    assert isinstance(n.output_variables["kafka_offsets"].value, UnresolvedValue)


@pytest.mark.asyncio
@pytest.mark.parametrize("store_enabled", [False, True])
async def test_execute_metadata_callback_and_store_policy(store_enabled):
    events = []
    store = CodecObjectStore(InMemoryBlobStore(default_ttl=600), DumpEngineCodec())
    n, gateway = node(
        store_enabled=store_enabled,
        data_store=store,
        on_node_metadata=lambda **kw: events.append(kw["metadata"]),
    )
    await n.execute(PipelineExecutionMode.FULL)
    assert not gateway.calls
    await n.resolve_metadata()
    result = n.output.compute(scheduler="threads")
    assert len(result) == 9
    if store_enabled:
        manifest = await store.get(dataframe_manifest_key(
            project_id=n.project_id,
            node_id=n.node_id,
            output_name="output",
            generation_id=n._dataframe_cache_generation_id,
        ))
        assert manifest is not None
        assert manifest.state == CacheGenerationState.READY
        assert sum(manifest.rows_per_partition) == len(result)
    else:
        assert n._dataframe_execution_cache is None
    assert events
    assert all(v.value_state == "resolved" for v in events[-1]["output_variables"].variables)
    assert all(
        v.value_state == "resolved"
        for v in (await n.resolve_metadata())["output_variables"].variables
    )


def test_changed_replay_invalidates_existing_references():
    n, gateway = node()
    n.process()
    n.output.compute()
    ref = n.output_variables["kafka_offsets"]
    gateway.records[0][0] = replace(gateway.records[0][0], value=b"xxx")
    with pytest.raises(Exception, match="changed"):
        n.output.compute()
    assert isinstance(ref.value, UnresolvedValue)


@pytest.mark.parametrize("failure", ["decode", "oversized", "cancel", "callback"])
def test_errors_do_not_publish(failure):
    n, gateway = node(max_message_bytes=4)
    if failure == "decode":
        gateway.records[0][0] = replace(gateway.records[0][0], value=b"\xff")
    if failure == "oversized":
        gateway.records[0][0] = replace(gateway.records[0][0], value=b"12345")
    n.process()
    if failure == "cancel":
        n._reader.check_cancelled = lambda: (_ for _ in ()).throw(NodeExecutionCancelled("stop"))
    if failure == "callback":

        async def fail(**_):
            raise ValueError("callback failed")

        n._metadata_cb = fail
    expected = {
        "decode": KafkaDecodeError,
        "oversized": KafkaMessageTooLargeError,
        "cancel": NodeExecutionCancelled,
        "callback": ValueError,
    }[failure]
    with pytest.raises(expected):
        n.output.compute()
    assert isinstance(n.output_variables["kafka_offsets"].value, UnresolvedValue)


def test_process_scheduler_rejected_before_payload():
    n, gateway = node()
    n.process()
    with pytest.raises((NotImplementedError, RuntimeError, TypeError), match=r"local|scheduler"):
        n.output.compute(scheduler="processes")
    assert not gateway.calls


def test_empty_snapshot_resolves_only_after_compute():
    n, _ = node(start_mode="latest")
    n.process()
    assert isinstance(n.output_variables["kafka_offsets"].value, UnresolvedValue)
    assert n.output.compute().empty
    assert n.output_variables["kafka_offsets"].value["partitions"] == []


def test_optimized_pruned_graph_cannot_publish_whole_plan():
    n, _ = node()
    n.process()
    selected = n.output.optimize().partitions[:2]
    assert len(selected.compute()) == 4
    assert isinstance(n.output_variables["kafka_offsets"].value, UnresolvedValue)
    assert len(n.output.compute()) == 9


def test_cancellation_between_chunks_invalidates_plan():
    from src.node_dsl.cancellation import CancellationToken

    stopped = [False]
    n, gateway = node()
    n._cancellation = CancellationToken(lambda: stopped[0])
    n.process()
    original = gateway.read

    def read(*args, **kwargs):
        batch = original(*args, **kwargs)
        stopped[0] = True
        return batch

    gateway.read = read
    with pytest.raises(NodeExecutionCancelled):
        n.output.compute()
    assert isinstance(n.output_variables["kafka_offsets"].value, UnresolvedValue)


@pytest.mark.asyncio
async def test_callback_failure_through_execute_reaches_sink():
    async def fail(**_):
        raise ValueError("metadata publication failed")

    n, _ = node(on_node_metadata=fail)
    await n.execute(PipelineExecutionMode.FULL)
    with pytest.raises(ValueError, match="metadata publication failed"):
        n.output.compute()
    assert isinstance(n.output_variables["kafka_offsets"].value, UnresolvedValue)


def test_replay_keeps_zero_byte_records_after_exact_byte_boundary():
    gateway = MemoryKafka({0: [(0, b"abc"), (1, None), (2, b"")]})
    n, _ = node(gateway, max_bytes=None)
    n.process()
    original = n.output.compute()
    pd.testing.assert_frame_equal(n.output.compute(), original)


def test_truncated_graph_is_error_not_snapshot_exhaustion():
    from src.modules.kafka_consumption.infra.exceptions import KafkaSnapshotLostError

    n, _ = node()
    n.process()
    n._reader.slots = 1
    n.output = n._reader.dataframe()
    with pytest.raises(KafkaSnapshotLostError, match="before terminal"):
        n.output.compute()
    assert isinstance(n.output_variables["kafka_offsets"].value, UnresolvedValue)


def test_unresolved_format_has_no_guessed_metadata():
    n, _ = node()
    n.value_format = UnresolvedValue()
    n.process_metadata()
    assert n.output is None
    assert n.infer_metadata()["output"] is None


def test_full_delayed_consumer_also_resolves_final_values():
    n, _ = node()
    n.process()
    parts = dask.compute(*n.output.to_delayed(), scheduler="threads")
    assert sum(len(part) for part in parts) == 9
    assert n.output_variables["kafka_offsets"].value["messages_read"] == 9


@pytest.mark.asyncio
async def test_existing_database_writer_finishes_after_publication(tmp_path):
    import sqlalchemy as sa

    from src.nodes.write.write_df_to_db_v3 import WriteDataFrameToDBV3

    n, _ = node()
    await n.execute(PipelineExecutionMode.FULL)
    engine = sa.create_engine("sqlite:///" + (tmp_path / "destination.sqlite").as_posix())
    observed = []
    try:
        with engine.begin() as connection:
            connection.execute(sa.text("CREATE TABLE events (value TEXT)"))
        writer = WriteDataFrameToDBV3(
            user_id="u", project_id="p", task_id="t", node_id="writer",
            connection=engine, df=n.output[["value"]], table_name="events",
            on_process_success=lambda **_: observed.append(
                n.output_variables["kafka_offsets"].value
            ),
        )
        await writer.execute(PipelineExecutionMode.FULL)
        with engine.connect() as connection:
            assert connection.scalar(sa.text("SELECT COUNT(*) FROM events")) == 9
        assert observed[0]["messages_read"] == 9
    finally:
        engine.dispose()
