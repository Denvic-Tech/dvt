import asyncio
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace

import dask.dataframe as dd
import numpy as np
import pandas as pd
import pytest
from dask import delayed

from src.modules.pipeline_cache import (
    CodecObjectStore,
    DumpEngineCodec,
    InMemoryBlobStore,
    InMemoryIndexStore,
)
from src.modules.pipeline_cache.domain.dataframe_cache import (
    DATAFRAME_CACHE_FORMAT_VERSION,
    ActiveDataFrameGeneration,
    DataFrameCachePolicy,
    DataFrameExecutionOrder,
    DataFramePartitionDescriptor,
    dataframe_active_key,
    dataframe_manifest_key,
    dataframe_partition_key,
)
from src.modules.pipeline_cache.domain.fingerprints import create_node_runtime_fingerprint
from src.modules.pipeline_cache.flow.dataframe_execution_cache import DataFrameExecutionCache
from src.modules.pipeline_cache.infra.dask_dataframe_cache import (
    DaskPartitionCacheWriter,
    _build_restore_batches,
)
from src.node_dsl import DFOutputBaseNode, InputField, OutputField
from src.pipeline.execution_mode import PipelineExecutionMode


def _data_store(default_ttl: int = 600):
    return CodecObjectStore(InMemoryBlobStore(default_ttl=default_ttl), DumpEngineCodec())


def _index_store(default_ttl: int = 600):
    codec = DumpEngineCodec()
    return InMemoryIndexStore(
        serializer=codec.dump,
        deserializer=codec.load,
        default_ttl=default_ttl,
        separator=":::",
    )


class _IdentityNode(DFOutputBaseNode):
    df_in: dd.DataFrame = InputField()
    output: dd.DataFrame = OutputField()

    def process(self) -> None:
        self.output = self.df_in


class _TwoOutputNode(DFOutputBaseNode):
    df_in: dd.DataFrame = InputField()
    output: dd.DataFrame = OutputField()
    secondary: dd.DataFrame = OutputField()

    def process(self) -> None:
        self.output = self.df_in
        self.secondary = self.df_in.assign(second=self.df_in.iloc[:, 0] * 2)


async def _execute_and_snapshot(node: DFOutputBaseNode, metadata: dict | None = None):
    await node.execute(PipelineExecutionMode.FULL)
    computed = {
        name: output.value.compute(scheduler="threads")
        for name, output in node.get_outputs().items()
        if isinstance(output.value, dd.DataFrame)
    }
    outputs = node.get_outputs()
    await node.cache_execution_snapshot(
        outputs=outputs,
        metadata=metadata or {name: {"cached": True} for name in outputs},
    )
    return computed, outputs


async def _active_manifest(store, node, output_name: str = "output"):
    active = await store.get(dataframe_active_key(project_id=node.project_id, node_id=node.node_id))
    assert isinstance(active, ActiveDataFrameGeneration)
    manifest = await store.get(dataframe_manifest_key(
        project_id=node.project_id,
        node_id=node.node_id,
        output_name=output_name,
        generation_id=active.generation_id,
    ))
    assert manifest is not None
    return active, manifest


@pytest.mark.asyncio
async def test_execution_cache_is_lossless_above_500k_rows() -> None:
    expected = pd.DataFrame({"value": np.arange(500_003, dtype=np.int64)})
    store = _data_store()
    index = _index_store()
    node = _IdentityNode(
        user_id="u", project_id="p", task_id="t", node_id="n",
        df_in=dd.from_pandas(expected, npartitions=1),
        data_store=store, data_index_store=index, store_enabled=True,
    )
    _, outputs = await _execute_and_snapshot(node)

    restored = await DFOutputBaseNode.restore_execution_snapshot(
        project_id="p", node_id="n", node_name=node.__class__.__name__,
        expected_output_names=tuple(outputs), data_store=store, data_index_store=index,
        node_runtime_fingerprint=create_node_runtime_fingerprint(node.__class__),
    )
    assert restored is not None
    actual = restored.outputs["output"].value.compute(scheduler="threads")
    assert len(actual) == 500_003
    pd.testing.assert_frame_equal(actual.reset_index(drop=True), expected)


def test_partition_keys_are_generation_scoped_not_content_hashes() -> None:
    keys = {
        dataframe_partition_key(project_id="p1", node_id="n1", output_name="o1", generation_id="g1", part_no=0),
        dataframe_partition_key(project_id="p2", node_id="n1", output_name="o1", generation_id="g1", part_no=0),
        dataframe_partition_key(project_id="p1", node_id="n2", output_name="o1", generation_id="g1", part_no=0),
        dataframe_partition_key(project_id="p1", node_id="n1", output_name="o2", generation_id="g1", part_no=0),
        dataframe_partition_key(project_id="p1", node_id="n1", output_name="o1", generation_id="g2", part_no=0),
        dataframe_partition_key(project_id="p1", node_id="n1", output_name="o1", generation_id="g1", part_no=1),
    }
    assert len(keys) == 6


def test_restore_batches_are_bounded_by_partition_count_and_payload_bytes() -> None:
    policy = DataFrameCachePolicy(
        max_restore_batch_partitions=3,
        max_restore_batch_bytes=100,
    )
    descriptors = tuple(
        DataFramePartitionDescriptor(
            part_no=index,
            cache_key=f"part-{index}",
            rows=1,
            payload_bytes=payload_bytes,
        )
        for index, payload_bytes in enumerate((30, 30, 30, 30, 150, 20))
    )

    batches = _build_restore_batches(SimpleNamespace(partitions=descriptors), policy)

    assert [[item.part_no for item in batch] for batch in batches] == [
        [0, 1, 2],
        [3],
        [4],
        [5],
    ]
    assert all(len(batch) <= 3 for batch in batches)
    assert all(
        sum(item.payload_bytes for item in batch) <= 100 or len(batch) == 1
        for batch in batches
    )


@pytest.mark.asyncio
async def test_incomplete_new_generation_never_replaces_previous_ready_generation() -> None:
    store = _data_store()
    cache = DataFrameExecutionCache(data_store=store)
    meta = pd.DataFrame({"value": pd.Series(dtype="int64")})
    runtime = "runtime:v1"
    old_order = DataFrameExecutionOrder(queued_at_us=1, task_id="old")

    gen1 = "generation-1"
    await cache.begin_output_generation(
        project_id="p", node_id="n", output_name="output", generation_id=gen1,
        node_runtime_fingerprint=runtime, meta=meta, npartitions=1,
        known_divisions=False, divisions=None,
    )
    payload = cache.encode_partition(pd.DataFrame({"value": [1]}))
    descriptor = await cache.put_encoded_partition(
        project_id="p", node_id="n", output_name="output", generation_id=gen1,
        part_no=0, rows=1, payload=payload,
    )
    await cache.commit_output_generation(
        project_id="p", node_id="n", output_name="output", generation_id=gen1,
        partitions=(descriptor,),
    )
    await cache.stage_execution_snapshot(
        project_id="p", node_id="n", generation_id=gen1, node_name="Node",
        node_runtime_fingerprint=runtime, output_names=("output",),
        dataframe_output_names=("output",), non_dataframe_outputs={}, metadata={"output": {}},
        execution_order=old_order,
    )
    active1 = await store.get(dataframe_active_key(project_id="p", node_id="n"))
    assert active1.generation_id == gen1

    gen2 = "generation-2"
    await cache.begin_output_generation(
        project_id="p", node_id="n", output_name="output", generation_id=gen2,
        node_runtime_fingerprint=runtime, meta=meta, npartitions=2,
        known_divisions=False, divisions=None,
    )
    await cache.stage_execution_snapshot(
        project_id="p", node_id="n", generation_id=gen2, node_name="Node",
        node_runtime_fingerprint=runtime, output_names=("output",),
        dataframe_output_names=("output",), non_dataframe_outputs={}, metadata={"output": {}},
        execution_order=DataFrameExecutionOrder(queued_at_us=2, task_id="new"),
    )
    active2 = await store.get(dataframe_active_key(project_id="p", node_id="n"))
    assert active2.generation_id == gen1


@pytest.mark.asyncio
async def test_restore_is_lazy_and_prefetch_is_bounded_on_compute() -> None:
    delegate = _data_store()
    index = _index_store()
    expected = pd.DataFrame({"value": np.arange(40)})
    node = _IdentityNode(
        user_id="u", project_id="lazy-p", task_id="t", node_id="lazy-n",
        df_in=dd.from_pandas(expected, npartitions=8), data_store=delegate,
        data_index_store=index, store_enabled=True,
    )
    _, outputs = await _execute_and_snapshot(node)

    class CountingStore:
        def __init__(self, wrapped):
            self.wrapped = wrapped
            self.get_keys: list[str] = []

        def encode(self, obj): return self.wrapped.encode(obj)
        def decode(self, payload): return self.wrapped.decode(payload)
        async def put(self, *a, **kw): return await self.wrapped.put(*a, **kw)
        async def put_encoded(self, *a, **kw): return await self.wrapped.put_encoded(*a, **kw)
        async def get_encoded(self, *a, **kw): return await self.wrapped.get_encoded(*a, **kw)
        async def get(self, key):
            self.get_keys.append(key)
            return await self.wrapped.get(key)
        async def has(self, key): return await self.wrapped.has(key)
        async def has_many(self, keys): return await self.wrapped.has_many(keys)
        async def remove(self, *a, **kw): return await self.wrapped.remove(*a, **kw)

    store = CountingStore(delegate)
    restored = await DFOutputBaseNode.restore_execution_snapshot(
        project_id=node.project_id, node_id=node.node_id, node_name=node.__class__.__name__,
        expected_output_names=tuple(outputs), data_store=store, data_index_store=index,
        node_runtime_fingerprint=create_node_runtime_fingerprint(node.__class__),
    )
    assert restored is not None
    before_compute = list(store.get_keys)
    assert not any(":part:" in key for key in before_compute)

    first = restored.outputs["output"].value.get_partition(0).compute(scheduler="threads")
    assert len(first) == 5
    partition_gets = [key for key in store.get_keys if ":part:" in key]
    assert 1 <= len(partition_gets) <= DataFrameCachePolicy().max_restore_batch_partitions


@pytest.mark.asyncio
async def test_missing_partition_turns_ready_generation_into_cache_miss() -> None:
    store = _data_store()
    index = _index_store()
    node = _IdentityNode(
        user_id="u", project_id="missing-p", task_id="t", node_id="missing-n",
        df_in=dd.from_pandas(pd.DataFrame({"value": range(10)}), npartitions=2),
        data_store=store, data_index_store=index, store_enabled=True,
    )
    _, outputs = await _execute_and_snapshot(node)
    _, manifest = await _active_manifest(store, node)
    await store.remove(manifest.partitions[0].cache_key)

    restored = await DFOutputBaseNode.restore_execution_snapshot(
        project_id=node.project_id, node_id=node.node_id, node_name=node.__class__.__name__,
        expected_output_names=tuple(outputs), data_store=store, data_index_store=index,
        node_runtime_fingerprint=create_node_runtime_fingerprint(node.__class__),
    )
    assert restored is None


@pytest.mark.asyncio
async def test_known_divisions_round_trip() -> None:
    pdf = pd.DataFrame({"value": np.arange(100)}, index=pd.Index(np.arange(100), name="id"))
    original = dd.from_pandas(pdf, npartitions=5, sort=True)
    assert original.known_divisions
    store, index = _data_store(), _index_store()
    node = _IdentityNode(
        user_id="u", project_id="div-p", task_id="t", node_id="div-n",
        df_in=original, data_store=store, data_index_store=index, store_enabled=True,
    )
    _, outputs = await _execute_and_snapshot(node)
    restored = await DFOutputBaseNode.restore_execution_snapshot(
        project_id=node.project_id, node_id=node.node_id, node_name=node.__class__.__name__,
        expected_output_names=tuple(outputs), data_store=store, data_index_store=index,
        node_runtime_fingerprint=create_node_runtime_fingerprint(node.__class__),
    )
    assert restored is not None
    cached = restored.outputs["output"].value
    assert cached.known_divisions
    assert cached.divisions == original.divisions
    pd.testing.assert_frame_equal(cached.loc[20:30].compute(), original.loc[20:30].compute())


@pytest.mark.asyncio
async def test_cache_partition_write_failure_is_fail_open() -> None:
    delegate = _data_store()

    class PartitionFailStore:
        def encode(self, obj): return delegate.encode(obj)
        def decode(self, payload): return delegate.decode(payload)
        async def put(self, *a, **kw): return await delegate.put(*a, **kw)
        async def get(self, *a, **kw): return await delegate.get(*a, **kw)
        async def has(self, *a, **kw): return await delegate.has(*a, **kw)
        async def has_many(self, *a, **kw): return await delegate.has_many(*a, **kw)
        async def remove(self, *a, **kw): return await delegate.remove(*a, **kw)
        async def put_encoded(self, *_a, **_kw):
            raise RuntimeError("cache backend unavailable")

    store = PartitionFailStore()
    index = _index_store()
    expected = pd.DataFrame({"value": range(20)})
    node = _IdentityNode(
        user_id="u", project_id="fail-p", task_id="t", node_id="fail-n",
        df_in=dd.from_pandas(expected, npartitions=4), data_store=store,
        data_index_store=index, store_enabled=True,
    )
    await node.execute(PipelineExecutionMode.FULL)
    actual = node.output.compute(scheduler="threads")
    pd.testing.assert_frame_equal(actual.reset_index(drop=True), expected)
    _, manifest = await _active_manifest(delegate, node) if await delegate.has(
        dataframe_active_key(project_id=node.project_id, node_id=node.node_id)
    ) else (None, None)
    assert manifest is None


@pytest.mark.asyncio
async def test_activation_cas_failure_is_fail_open_and_strict_mode_propagates() -> None:
    delegate = _data_store()

    class ActivationFailStore:
        def encode(self, obj): return delegate.encode(obj)
        def decode(self, payload): return delegate.decode(payload)
        async def put(self, *a, **kw): return await delegate.put(*a, **kw)
        async def put_encoded(self, *a, **kw): return await delegate.put_encoded(*a, **kw)
        async def get(self, *a, **kw): return await delegate.get(*a, **kw)
        async def get_encoded(self, *a, **kw): return await delegate.get_encoded(*a, **kw)
        async def has(self, *a, **kw): return await delegate.has(*a, **kw)
        async def has_many(self, *a, **kw): return await delegate.has_many(*a, **kw)
        async def remove(self, *a, **kw): return await delegate.remove(*a, **kw)
        async def compare_and_set_encoded(self, *_a, **_kw):
            raise RuntimeError("activation CAS unavailable")

    async def exercise(*, strict: bool) -> None:
        node = _IdentityNode(
            user_id="u", project_id=f"cas-fail-{strict}", task_id="t", node_id="n",
            df_in=dd.from_pandas(pd.DataFrame({"value": range(8)}), npartitions=2),
            data_store=ActivationFailStore(), data_index_store=_index_store(), store_enabled=True,
            dataframe_cache_policy=DataFrameCachePolicy(strict=strict),
        )
        await node.execute(PipelineExecutionMode.FULL)
        actual = node.output.compute(scheduler="threads")
        assert len(actual) == 8
        await node.cache_execution_snapshot(
            outputs=node.get_outputs(), metadata={"output": {"cached": True}}
        )

    await exercise(strict=False)
    with pytest.raises(RuntimeError, match="activation CAS unavailable"):
        await exercise(strict=True)


@pytest.mark.asyncio
async def test_partition_is_serialized_before_mutable_dataframe_lifetime_ends() -> None:
    store = _data_store()
    cache = DataFrameExecutionCache(data_store=store)
    generation = "g"
    meta = pd.DataFrame({"value": pd.Series(dtype="int64")})
    await cache.begin_output_generation(
        project_id="p", node_id="n", output_name="output", generation_id=generation,
        node_runtime_fingerprint="runtime", meta=meta, npartitions=1,
        known_divisions=False, divisions=None,
    )
    writer = DaskPartitionCacheWriter(
        cache=cache, project_id="p", node_id="n", output_name="output",
        generation_id=generation, npartitions=1,
        policy=DataFrameCachePolicy(max_pending_partitions=1, max_pending_bytes=1024 * 1024),
    )
    partition = pd.DataFrame({"value": [1, 2, 3]})
    writer.submit_partition(partition, part_no=0)
    partition.loc[:, "value"] = 999
    assert writer.finish()

    manifest = await store.get(dataframe_manifest_key(
        project_id="p", node_id="n", output_name="output", generation_id=generation,
    ))
    cached = await store.get(manifest.partitions[0].cache_key)
    assert cached["value"].tolist() == [1, 2, 3]


@pytest.mark.asyncio
async def test_multiple_dataframe_outputs_use_same_generation_without_mixing() -> None:
    store, index = _data_store(), _index_store()
    pdf = pd.DataFrame({"value": range(12)})
    node = _TwoOutputNode(
        user_id="u", project_id="multi-p", task_id="t", node_id="multi-n",
        df_in=dd.from_pandas(pdf, npartitions=3), data_store=store,
        data_index_store=index, store_enabled=True,
    )
    _, outputs = await _execute_and_snapshot(node, {"output": {}, "secondary": {}})
    active = await store.get(dataframe_active_key(project_id=node.project_id, node_id=node.node_id))
    assert isinstance(active, ActiveDataFrameGeneration)
    manifests = []
    for output_name in ("output", "secondary"):
        manifest = await store.get(dataframe_manifest_key(
            project_id=node.project_id, node_id=node.node_id, output_name=output_name,
            generation_id=active.generation_id,
        ))
        manifests.append(manifest)
        assert manifest.generation_id == active.generation_id
        assert all(f":{output_name}:{active.generation_id}:part:" in p.cache_key for p in manifest.partitions)

    restored = await DFOutputBaseNode.restore_execution_snapshot(
        project_id=node.project_id, node_id=node.node_id, node_name=node.__class__.__name__,
        expected_output_names=tuple(outputs), data_store=store, data_index_store=index,
        node_runtime_fingerprint=create_node_runtime_fingerprint(node.__class__),
    )
    assert restored is not None
    assert set(restored.outputs) == set(outputs)


@pytest.mark.asyncio
async def test_stale_multi_output_generation_cannot_replace_newer_active_generation() -> None:
    store = _data_store()
    cache = DataFrameExecutionCache(data_store=store)
    meta = pd.DataFrame({"value": pd.Series(dtype="int64")})

    async def complete(generation: str, order: DataFrameExecutionOrder, value: int) -> None:
        for output_name in ("output", "secondary"):
            await cache.begin_output_generation(
                project_id="p", node_id="n", output_name=output_name,
                generation_id=generation, node_runtime_fingerprint="runtime",
                meta=meta, npartitions=1, known_divisions=False, divisions=None,
            )
            descriptor = await cache.put_encoded_partition(
                project_id="p", node_id="n", output_name=output_name,
                generation_id=generation, part_no=0, rows=1,
                payload=cache.encode_partition(pd.DataFrame({"value": [value]})),
            )
            await cache.commit_output_generation(
                project_id="p", node_id="n", output_name=output_name,
                generation_id=generation, partitions=(descriptor,),
            )
        await cache.stage_execution_snapshot(
            project_id="p", node_id="n", generation_id=generation, node_name="Node",
            node_runtime_fingerprint="runtime", output_names=("output", "secondary"),
            dataframe_output_names=("output", "secondary"), non_dataframe_outputs={},
            metadata={"output": {}, "secondary": {}}, execution_order=order,
        )

    await complete("new", DataFrameExecutionOrder(2, "new"), 2)
    await complete("old", DataFrameExecutionOrder(1, "old"), 1)

    active = await store.get(dataframe_active_key(project_id="p", node_id="n"))
    assert active.generation_id == "new"


@pytest.mark.asyncio
@pytest.mark.parametrize("rows,npartitions", [(0, 1), (1, 1), (100, 100)])
async def test_empty_single_and_many_partitions_round_trip(rows: int, npartitions: int) -> None:
    store, index = _data_store(), _index_store()
    pdf = pd.DataFrame({"value": np.arange(rows, dtype=np.int64)})
    ddf = dd.from_pandas(pdf, npartitions=npartitions)
    node = _IdentityNode(
        user_id="u", project_id=f"shape-p-{rows}-{npartitions}", task_id="t", node_id="n",
        df_in=ddf, data_store=store, data_index_store=index, store_enabled=True,
    )
    _, outputs = await _execute_and_snapshot(node)
    restored = await DFOutputBaseNode.restore_execution_snapshot(
        project_id=node.project_id, node_id=node.node_id, node_name=node.__class__.__name__,
        expected_output_names=tuple(outputs), data_store=store, data_index_store=index,
        node_runtime_fingerprint=create_node_runtime_fingerprint(node.__class__),
    )
    assert restored is not None
    actual = restored.outputs["output"].value.compute(scheduler="threads")
    pd.testing.assert_frame_equal(actual.reset_index(drop=True), pdf)


@pytest.mark.asyncio
async def test_empty_partition_is_cached_and_restored_without_being_dropped() -> None:
    store, index = _data_store(), _index_store()
    meta = pd.DataFrame({"value": pd.Series(dtype="int64")})
    parts = [
        delayed(lambda: pd.DataFrame({"value": [1, 2]}))(),
        delayed(lambda: meta.copy())(),
        delayed(lambda: pd.DataFrame({"value": [3]}))(),
    ]
    ddf = dd.from_delayed(parts, meta=meta)
    node = _IdentityNode(
        user_id="u", project_id="empty-part-p", task_id="t", node_id="n",
        df_in=ddf, data_store=store, data_index_store=index, store_enabled=True,
    )
    _, outputs = await _execute_and_snapshot(node)
    _, manifest = await _active_manifest(store, node)

    assert manifest.npartitions == 3
    assert manifest.rows_per_partition == (2, 0, 1)

    restored = await DFOutputBaseNode.restore_execution_snapshot(
        project_id=node.project_id,
        node_id=node.node_id,
        node_name=node.__class__.__name__,
        expected_output_names=tuple(outputs),
        data_store=store,
        data_index_store=index,
        node_runtime_fingerprint=create_node_runtime_fingerprint(node.__class__),
    )
    assert restored is not None
    assert restored.outputs["output"].value.npartitions == 3
    actual = restored.outputs["output"].value.compute(scheduler="threads")
    assert actual["value"].tolist() == [1, 2, 3]


@pytest.mark.asyncio
async def test_cache_disabled_does_not_write_dataframe_cache_keys() -> None:
    store, index = _data_store(), _index_store()
    node = _IdentityNode(
        user_id="u", project_id="disabled-p", task_id="t", node_id="disabled-n",
        df_in=dd.from_pandas(pd.DataFrame({"value": range(20)}), npartitions=4),
        data_store=store,
        data_index_store=index,
        store_enabled=False,
    )

    await node.execute(PipelineExecutionMode.FULL)
    actual = node.output.compute(scheduler="threads")

    assert len(actual) == 20
    assert await store.keys("df:disabled-p:disabled-n:") == []


@pytest.mark.asyncio
async def test_project_ttl_is_propagated_to_dataframe_generation_writes() -> None:
    delegate = _data_store()

    class RecordingStore:
        def __init__(self, wrapped):
            self.wrapped = wrapped
            self.ttls: list[int | None] = []

        def encode(self, obj): return self.wrapped.encode(obj)
        def decode(self, payload): return self.wrapped.decode(payload)
        async def put(self, key, obj, ttl_lifetime=None):
            self.ttls.append(ttl_lifetime)
            return await self.wrapped.put(key, obj, ttl_lifetime)
        async def put_encoded(self, key, payload, ttl_lifetime=None):
            self.ttls.append(ttl_lifetime)
            return await self.wrapped.put_encoded(key, payload, ttl_lifetime)
        async def compare_and_set_encoded(
            self, key, *, expected, payload, ttl_lifetime=None
        ):
            self.ttls.append(ttl_lifetime)
            return await self.wrapped.compare_and_set_encoded(
                key,
                expected=expected,
                payload=payload,
                ttl_lifetime=ttl_lifetime,
            )
        async def get(self, *a, **kw): return await self.wrapped.get(*a, **kw)
        async def get_encoded(self, *a, **kw): return await self.wrapped.get_encoded(*a, **kw)
        async def has(self, *a, **kw): return await self.wrapped.has(*a, **kw)
        async def has_many(self, *a, **kw): return await self.wrapped.has_many(*a, **kw)
        async def keys(self, *a, **kw): return await self.wrapped.keys(*a, **kw)
        async def remove(self, *a, **kw): return await self.wrapped.remove(*a, **kw)

    store = RecordingStore(delegate)
    index = _index_store()
    node = _IdentityNode(
        user_id="u", project_id="ttl-p", task_id="t", node_id="ttl-n",
        df_in=dd.from_pandas(pd.DataFrame({"value": range(10)}), npartitions=2),
        data_store=store,
        data_index_store=index,
        store_enabled=True,
        project_settings=type("ProjectSettings", (), {"ttl_time": 17})(),
    )

    await _execute_and_snapshot(node)

    assert store.ttls
    assert all(ttl == 17 for ttl in store.ttls)
    assert await delegate.has(dataframe_active_key(project_id=node.project_id, node_id=node.node_id))


@pytest.mark.asyncio
async def test_large_wide_dataframe_round_trip() -> None:
    rows = 12_000
    columns = 96
    pdf = pd.DataFrame(
        np.arange(rows * columns, dtype=np.float64).reshape(rows, columns),
        columns=[f"c{i}" for i in range(columns)],
    )
    assert int(pdf.memory_usage(index=True, deep=True).sum()) > 8 * 1024 * 1024
    store, index = _data_store(), _index_store()
    node = _IdentityNode(
        user_id="u", project_id="wide-p", task_id="t", node_id="wide-n",
        df_in=dd.from_pandas(pdf, npartitions=2),
        data_store=store,
        data_index_store=index,
        store_enabled=True,
    )
    _, outputs = await _execute_and_snapshot(node)
    restored = await DFOutputBaseNode.restore_execution_snapshot(
        project_id=node.project_id,
        node_id=node.node_id,
        node_name=node.__class__.__name__,
        expected_output_names=tuple(outputs),
        data_store=store,
        data_index_store=index,
        node_runtime_fingerprint=create_node_runtime_fingerprint(node.__class__),
    )

    assert restored is not None
    actual = restored.outputs["output"].value.compute(scheduler="threads")
    pd.testing.assert_frame_equal(actual, pdf)


@pytest.mark.asyncio
async def test_format_and_runtime_version_mismatch_are_cache_misses() -> None:
    store, index = _data_store(), _index_store()
    node = _IdentityNode(
        user_id="u", project_id="version-p", task_id="t", node_id="version-n",
        df_in=dd.from_pandas(pd.DataFrame({"value": [1, 2]}), npartitions=1),
        data_store=store, data_index_store=index, store_enabled=True,
    )
    _, outputs = await _execute_and_snapshot(node)
    active, manifest = await _active_manifest(store, node)

    wrong_runtime = await DFOutputBaseNode.restore_execution_snapshot(
        project_id=node.project_id, node_id=node.node_id, node_name=node.__class__.__name__,
        expected_output_names=tuple(outputs), data_store=store, data_index_store=index,
        node_runtime_fingerprint="node_runtime:different",
    )
    assert wrong_runtime is None

    await store.put(dataframe_manifest_key(
        project_id=node.project_id, node_id=node.node_id, output_name="output",
        generation_id=active.generation_id,
    ), replace(manifest, format_version=DATAFRAME_CACHE_FORMAT_VERSION + 1))
    wrong_format = await DFOutputBaseNode.restore_execution_snapshot(
        project_id=node.project_id, node_id=node.node_id, node_name=node.__class__.__name__,
        expected_output_names=tuple(outputs), data_store=store, data_index_store=index,
        node_runtime_fingerprint=create_node_runtime_fingerprint(node.__class__),
    )
    assert wrong_format is None


@pytest.mark.asyncio
async def test_parallel_activation_keeps_newer_execution_active_and_never_mixes_namespaces() -> None:
    store = _data_store()
    cache = DataFrameExecutionCache(data_store=store)
    meta = pd.DataFrame({"value": pd.Series(dtype="int64")})

    async def write_generation(
        generation: str,
        value: int,
        execution_order: DataFrameExecutionOrder,
        before_snapshot: asyncio.Event,
        allow_snapshot: asyncio.Event,
    ):
        await cache.begin_output_generation(
            project_id="p", node_id="n", output_name="output", generation_id=generation,
            node_runtime_fingerprint="runtime", meta=meta, npartitions=2,
            known_divisions=False, divisions=None,
        )
        descriptors = []
        for part_no in range(2):
            payload = cache.encode_partition(pd.DataFrame({"value": [value, part_no]}))
            descriptors.append(await cache.put_encoded_partition(
                project_id="p", node_id="n", output_name="output", generation_id=generation,
                part_no=part_no, rows=2, payload=payload,
            ))
        await cache.commit_output_generation(
            project_id="p", node_id="n", output_name="output", generation_id=generation,
            partitions=tuple(descriptors),
        )
        before_snapshot.set()
        await allow_snapshot.wait()
        await cache.stage_execution_snapshot(
            project_id="p", node_id="n", generation_id=generation, node_name="Node",
            node_runtime_fingerprint="runtime", output_names=("output",),
            dataframe_output_names=("output",), non_dataframe_outputs={}, metadata={"output": {}},
            execution_order=execution_order,
        )
        return descriptors

    old_ready = asyncio.Event()
    new_ready = asyncio.Event()
    allow_old = asyncio.Event()
    allow_new = asyncio.Event()
    old_task = asyncio.create_task(write_generation(
        "ga", 10, DataFrameExecutionOrder(queued_at_us=1, task_id="old"), old_ready, allow_old
    ))
    new_task = asyncio.create_task(write_generation(
        "gb", 20, DataFrameExecutionOrder(queued_at_us=2, task_id="new"), new_ready, allow_new
    ))
    await asyncio.gather(old_ready.wait(), new_ready.wait())
    allow_new.set()
    await asyncio.sleep(0)
    allow_old.set()
    first, second = await asyncio.gather(old_task, new_task)
    assert all(":ga:part:" in item.cache_key for item in first)
    assert all(":gb:part:" in item.cache_key for item in second)
    active = await store.get(dataframe_active_key(project_id="p", node_id="n"))
    assert active.generation_id == "gb"
    assert active.execution_order == DataFrameExecutionOrder(queued_at_us=2, task_id="new")


@pytest.mark.asyncio
async def test_old_execution_finishing_first_is_replaced_by_newer_execution() -> None:
    store = _data_store()
    cache = DataFrameExecutionCache(data_store=store)
    meta = pd.DataFrame({"value": pd.Series(dtype="int64")})

    async def complete(generation: str, order: DataFrameExecutionOrder, value: int) -> None:
        await cache.begin_output_generation(
            project_id="p", node_id="n", output_name="output", generation_id=generation,
            node_runtime_fingerprint="runtime", meta=meta, npartitions=1,
            known_divisions=False, divisions=None,
        )
        descriptor = await cache.put_encoded_partition(
            project_id="p", node_id="n", output_name="output", generation_id=generation,
            part_no=0, rows=1,
            payload=cache.encode_partition(pd.DataFrame({"value": [value]})),
        )
        await cache.commit_output_generation(
            project_id="p", node_id="n", output_name="output", generation_id=generation,
            partitions=(descriptor,),
        )
        await cache.stage_execution_snapshot(
            project_id="p", node_id="n", generation_id=generation, node_name="Node",
            node_runtime_fingerprint="runtime", output_names=("output",),
            dataframe_output_names=("output",), non_dataframe_outputs={}, metadata={"output": {}},
            execution_order=order,
        )

    await complete("old-generation", DataFrameExecutionOrder(1, "old"), 1)
    await complete("new-generation", DataFrameExecutionOrder(2, "new"), 2)
    active = await store.get(dataframe_active_key(project_id="p", node_id="n"))
    assert active.generation_id == "new-generation"


@pytest.mark.asyncio
async def test_same_execution_order_only_allows_idempotent_same_generation() -> None:
    store = _data_store()
    cache = DataFrameExecutionCache(data_store=store)
    order = DataFrameExecutionOrder(queued_at_us=10, task_id="task")
    assert await cache._activate_if_newer(
        project_id="p", node_id="n", generation_id="g1", execution_order=order
    )
    assert await cache._activate_if_newer(
        project_id="p", node_id="n", generation_id="g1", execution_order=order
    )
    assert not await cache._activate_if_newer(
        project_id="p", node_id="n", generation_id="g2", execution_order=order
    )
    active = await store.get(dataframe_active_key(project_id="p", node_id="n"))
    assert active.generation_id == "g1"


@pytest.mark.parametrize(
    "pdf",
    [
        pd.DataFrame({"decimal": pd.Series([Decimal("1.10"), 2, 3.5, None], dtype=object)}),
        pd.DataFrame({"nullable_int": pd.Series([1, None, 3], dtype="Int64")}),
        pd.DataFrame({"nullable_bool": pd.Series([True, None, False], dtype="boolean")}),
        pd.DataFrame({"string": pd.Series(["a", None, "c"], dtype="string")}),
        pd.DataFrame({"dt": pd.to_datetime(["2020-01-01", None, "2020-01-03"])}),
        pd.DataFrame({"dt_tz": pd.to_datetime(["2020-01-01", None, "2020-01-03"], utc=True)}),
        pd.DataFrame({"category": pd.Series(["a", "b", "a"], dtype="category")}),
        pd.DataFrame({"json": pd.Series([{"a": 1}, [1, 2], None], dtype=object)}),
        pd.DataFrame(
            {"value": [1, 2, 3, 4]},
            index=pd.MultiIndex.from_tuples([("a", 1), ("a", 2), ("b", 1), ("b", 2)], names=["group", "id"]),
        ),
        pd.DataFrame({"value": [1, 2]}, index=pd.Index([10, 20], dtype="int64", name="custom_id")),
    ],
)
def test_execution_codec_preserves_dataframe_fidelity(pdf: pd.DataFrame) -> None:
    codec = DumpEngineCodec()
    restored = codec.load(codec.dump(pdf))
    pd.testing.assert_frame_equal(restored, pdf, check_dtype=True, check_categorical=True)
    if "decimal" in pdf:
        assert isinstance(restored["decimal"].iloc[0], Decimal)
        assert restored["decimal"].iloc[0] == Decimal("1.10")
