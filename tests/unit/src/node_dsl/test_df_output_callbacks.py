import threading

import dask.dataframe as dd
import pandas as pd
import pytest

import src.node_dsl.base_node.df_output as df_output_module
from src.modules.pipeline_cache import (
    CodecObjectStore,
    DumpEngineCodec,
    InMemoryBlobStore,
    InMemoryIndexStore,
)
from src.modules.pipeline_cache.domain.dataframe_cache import (
    ActiveDataFrameGeneration,
    DataFrameCacheManifest,
    dataframe_active_key,
    dataframe_manifest_key,
)
from src.node_dsl import DFOutputBaseNode, InputField, OutputField
from src.pipeline.execution_mode import PipelineExecutionMode


def _build_data_store() -> CodecObjectStore[pd.DataFrame]:
    return CodecObjectStore(
        InMemoryBlobStore(default_ttl=600),
        DumpEngineCodec(),
    )


def _build_data_index_store() -> InMemoryIndexStore:
    codec = DumpEngineCodec()
    return InMemoryIndexStore(
        serializer=codec.dump,
        deserializer=codec.load,
        default_ttl=600,
        separator=":::",
    )


async def _get_manifest(data_store, *, project_id: str, node_id: str, output_name: str = "output"):
    active = await data_store.get(dataframe_active_key(project_id=project_id, node_id=node_id))
    assert isinstance(active, ActiveDataFrameGeneration)
    manifest = await data_store.get(dataframe_manifest_key(
        project_id=project_id,
        node_id=node_id,
        output_name=output_name,
        generation_id=active.generation_id,
    ))
    assert isinstance(manifest, DataFrameCacheManifest)
    return manifest


class _CallbacksTestNode(DFOutputBaseNode):
    df_in: dd.DataFrame = InputField()
    output: dd.DataFrame = OutputField()

    def process(self) -> None:
        self.output = self.df_in.assign(__tmp=self.df_in["value"] + 1).drop(columns="__tmp")


class _SourceOnlyCallbacksTestNode(DFOutputBaseNode):
    df_in: dd.DataFrame = InputField()
    output: dd.DataFrame = OutputField()

    def process(self) -> None:
        self.output = self.df_in


@pytest.mark.asyncio
async def test_df_output_callbacks_cache_progress_and_lifecycle() -> None:
    data_store = _build_data_store()
    data_index_store = _build_data_index_store()

    events = {"started": 0, "finished": 0, "progress_calls": 0}

    def _on_start(**_kwargs) -> None:
        events["started"] += 1

    def _on_success(**_kwargs) -> None:
        events["finished"] += 1

    def _on_progress(**_kwargs) -> None:
        events["progress_calls"] += 1

    ddf = dd.from_pandas(pd.DataFrame({"value": [1, 2, 3, 4]}), npartitions=2)
    node = _CallbacksTestNode(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="node",
        df_in=ddf,
        data_store=data_store,
        data_index_store=data_index_store,
        store_enabled=True,
        on_process_start=_on_start,
        on_process_success=_on_success,
        on_progress_step=_on_progress,
    )

    await node.execute(PipelineExecutionMode.FULL)
    assert events["started"] == 0
    assert events["finished"] == 0
    assert events["progress_calls"] == 0

    result = node.output.compute(scheduler="threads")
    assert len(result) == 4

    assert events["started"] == 1
    assert events["finished"] == 1
    assert events["progress_calls"] == 2

    await node.cache_execution_snapshot(outputs=node.get_outputs(), metadata=await node.resolve_metadata())
    manifest = await _get_manifest(data_store, project_id="project", node_id="node")
    assert manifest.npartitions == 2
    assert [entry.part_no for entry in manifest.partitions] == [0, 1]
    for entry in manifest.partitions:
        cached_partition = await data_store.get(entry.cache_key)
        assert isinstance(cached_partition, pd.DataFrame)
    assert isinstance(manifest.meta, pd.DataFrame)


@pytest.mark.asyncio
async def test_df_output_callbacks_for_source_only_expression() -> None:
    data_store = _build_data_store()
    data_index_store = _build_data_index_store()

    events = {"started": 0, "finished": 0, "progress_calls": 0}

    def _on_start(**_kwargs) -> None:
        events["started"] += 1

    def _on_success(**_kwargs) -> None:
        events["finished"] += 1

    def _on_progress(**_kwargs) -> None:
        events["progress_calls"] += 1

    ddf = dd.from_pandas(pd.DataFrame({"value": [1, 2, 3, 4]}), npartitions=2)
    node = _SourceOnlyCallbacksTestNode(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="node",
        df_in=ddf,
        data_store=data_store,
        data_index_store=data_index_store,
        store_enabled=True,
        on_process_start=_on_start,
        on_process_success=_on_success,
        on_progress_step=_on_progress,
    )

    await node.execute(PipelineExecutionMode.FULL)
    assert events["started"] == 0
    assert events["finished"] == 0
    assert events["progress_calls"] == 0

    result = node.output.compute(scheduler="threads")
    assert len(result) == 4

    assert events["started"] == 1
    assert events["finished"] == 1
    assert events["progress_calls"] == 2

    await node.cache_execution_snapshot(outputs=node.get_outputs(), metadata=await node.resolve_metadata())
    manifest = await _get_manifest(data_store, project_id="project", node_id="node")
    assert manifest.npartitions == 2
    for entry in manifest.partitions:
        cached_partition = await data_store.get(entry.cache_key)
        assert isinstance(cached_partition, pd.DataFrame)


@pytest.mark.asyncio
async def test_df_output_execution_snapshot_restores_complete_dataframe_cache() -> None:
    data_store = _build_data_store()
    data_index_store = _build_data_index_store()
    expected = pd.DataFrame({"value": [1, 2, 3, 4]})
    node = _SourceOnlyCallbacksTestNode(
        user_id="user",
        project_id="project-snapshot",
        task_id="task",
        node_id="node",
        df_in=dd.from_pandas(expected, npartitions=2),
        data_store=data_store,
        data_index_store=data_index_store,
        store_enabled=True,
    )

    await node.execute(PipelineExecutionMode.FULL)
    node.output.compute(scheduler="threads")
    outputs = node.get_outputs()
    metadata = await node.resolve_metadata()
    await node.cache_execution_snapshot(
        outputs=outputs,
        metadata=metadata,
    )

    restored = await DFOutputBaseNode.restore_execution_snapshot(
        project_id=node.project_id,
        node_id=node.node_id,
        node_name=node.__class__.__name__,
        expected_output_names=tuple(outputs),
        data_store=data_store,
        data_index_store=data_index_store,
    )

    assert restored is not None
    pd.testing.assert_frame_equal(
        restored.outputs["output"].value.compute(scheduler="threads").reset_index(drop=True),
        expected,
    )


@pytest.mark.asyncio
async def test_df_output_execution_snapshot_rejects_missing_partition() -> None:
    data_store = _build_data_store()
    data_index_store = _build_data_index_store()
    node = _SourceOnlyCallbacksTestNode(
        user_id="user",
        project_id="project-incomplete-snapshot",
        task_id="task",
        node_id="node",
        df_in=dd.from_pandas(pd.DataFrame({"value": [1, 2, 3, 4]}), npartitions=2),
        data_store=data_store,
        data_index_store=data_index_store,
        store_enabled=True,
    )

    await node.execute(PipelineExecutionMode.FULL)
    node.output.compute(scheduler="threads")
    outputs = node.get_outputs()
    await node.cache_execution_snapshot(
        outputs=outputs,
        metadata=await node.resolve_metadata(),
    )
    manifest = await _get_manifest(data_store, project_id=node.project_id, node_id=node.node_id)
    await data_store.remove(manifest.partitions[0].cache_key)

    restored = await DFOutputBaseNode.restore_execution_snapshot(
        project_id=node.project_id,
        node_id=node.node_id,
        node_name=node.__class__.__name__,
        expected_output_names=tuple(outputs),
        data_store=data_store,
        data_index_store=data_index_store,
    )

    assert restored is None


def test_on_operation_partition_delegates_to_bounded_writer() -> None:
    progress_calls = {"count": 0}
    submitted: list[tuple[pd.DataFrame, int]] = []

    def _progress_step() -> None:
        progress_calls["count"] += 1

    class _Writer:
        def submit_partition(self, partition: pd.DataFrame, *, part_no: int) -> None:
            submitted.append((partition, part_no))

    context = df_output_module.DDFPartitionCallbackContext(
        writer=_Writer(),
        progress_step=_progress_step,
        progress_lock=threading.Lock(),
    )

    df_output_module._on_operation_partition(
        pd.DataFrame({"value": [1, 2]}),
        "operation-id",
        partition_context=context,
        partition_info={"number": 3},
    )

    assert progress_calls["count"] == 1
    assert len(submitted) == 1
    assert submitted[0][1] == 3
