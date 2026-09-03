from __future__ import annotations

import pandas as pd
import pytest

from core.dump_engine import dump, load

from src.modules.pipeline_cache.domain.dataframe_cache import (
    DataFrameExecutionOrder,
    dataframe_active_key,
)
from src.modules.pipeline_cache.domain.entities import (
    DataIndexEntry,
    DDFMetaIndexEntry,
    MetadataCacheEntry,
    PDFIndexEntry,
)
from src.modules.pipeline_cache.domain.keys import DDFMetaKey, JSONKey, MetaKey, PDFKey
from src.modules.pipeline_cache.domain.value_objects import CacheNamespaces, PipelineCacheSettings
from src.modules.pipeline_cache.flow import PipelineCacheFacade, PipelineCacheProvider
from src.modules.pipeline_cache.flow.dataframe_execution_cache import DataFrameExecutionCache
from src.modules.pipeline_cache.infra import (
    CodecObjectStore,
    DumpEngineCodec,
    InMemoryBlobStore,
    InMemoryIndexStore,
)


class _MetadataRefreshGateway:
    async def enqueue_metadata_refresh(self, *, project_id: str, node_ids: list[str] | None = None) -> str | None:
        return f"task:{project_id}:{','.join(node_ids or ['all'])}"


def _build_provider() -> PipelineCacheProvider:
    settings = PipelineCacheSettings(
        namespaces=CacheNamespaces(
            data="data_store",
            data_index="data_index_store",
            metadata="metadata_store",
            metadata_index="metadata_index_store",
        ),
        default_ttl=600,
        index_separator=":::",
    )
    return PipelineCacheProvider(
        settings=settings,
        data_blob_store=InMemoryBlobStore(default_ttl=settings.default_ttl),
        data_index_store=InMemoryIndexStore(
            serializer=dump,
            deserializer=load,
            default_ttl=settings.default_ttl,
            separator=settings.index_separator,
        ),
        metadata_blob_store=InMemoryBlobStore(default_ttl=settings.default_ttl),
        metadata_index_store=InMemoryIndexStore(
            serializer=lambda value: value.encode("utf-8"),
            deserializer=lambda payload: payload.decode("utf-8"),
            default_ttl=settings.default_ttl,
            separator=settings.index_separator,
        ),
        data_codec=DumpEngineCodec(),
        metadata_codec=DumpEngineCodec(dump_kwargs={"mode": "meta"}),
        metadata_refresh_gateway=_MetadataRefreshGateway(),
    )


@pytest.mark.asyncio
async def test_facade_clear_data_cache_removes_selected_nodes() -> None:
    provider = _build_provider()
    facade = provider.create_facade()

    meta_key = facade.create_node_output_fingerprint("project-1", "node-1", "output")
    await facade.put_data_entry(
        cache_key=meta_key,
        value=pd.DataFrame({"value": pd.Series(dtype="int64")}),
        index_entries=[
            (
                DDFMetaKey(project_id="project-1", node_id="node-1", output_name="output"),
                DDFMetaIndexEntry(cache_key=meta_key, output_name="output", hashed_inputs=None),
            )
        ],
    )
    await facade.put_data_entry(
        cache_key="df-part-1",
        value=pd.DataFrame({"value": [1]}),
        index_entries=[
            (
                PDFKey(project_id="project-1", node_id="node-1", output_name="output", part_no=1),
                PDFIndexEntry(
                    cache_key="df-part-1",
                    output_name="output",
                    part_no=1,
                    total_parts=1,
                    rows=1,
                ),
            ),
        ],
    )
    await facade.put_data_entry(
        cache_key="cache-foreign",
        value={"value": "keep"},
        index_entries=[
            (
                JSONKey(project_id="project-2", node_id="node-foreign", output_name="out"),
                DataIndexEntry(cache_key="cache-foreign", output_name="out"),
            )
        ],
    )

    result = await facade.clear_data_cache(project_id="project-1", node_ids=["node-1"])

    assert result.cleared_keys == ["df-part-1", meta_key]
    assert await provider.data_blob_store.has("df-part-1") is False
    assert await provider.data_blob_store.has(meta_key) is False
    assert await provider.data_blob_store.has("cache-foreign") is True


@pytest.mark.asyncio
async def test_facade_clear_data_cache_removes_all_dataframe_generations_for_node() -> None:
    provider = _build_provider()
    facade = provider.create_facade()
    object_store = CodecObjectStore(provider.data_blob_store, provider.data_codec)
    cache = DataFrameExecutionCache(data_store=object_store)

    for generation_id, value in (("generation-old", 1), ("generation-active", 2)):
        await cache.begin_output_generation(
            project_id="project-1",
            node_id="node-1",
            output_name="output",
            generation_id=generation_id,
            node_runtime_fingerprint="runtime:test",
            meta=pd.DataFrame({"value": pd.Series(dtype="int64")}),
            npartitions=1,
            known_divisions=False,
            divisions=None,
        )
        descriptor = await cache.put_encoded_partition(
            project_id="project-1",
            node_id="node-1",
            output_name="output",
            generation_id=generation_id,
            part_no=0,
            rows=1,
            payload=cache.encode_partition(pd.DataFrame({"value": [value]})),
        )
        await cache.commit_output_generation(
            project_id="project-1",
            node_id="node-1",
            output_name="output",
            generation_id=generation_id,
            partitions=(descriptor,),
        )
        await cache.stage_execution_snapshot(
            project_id="project-1",
            node_id="node-1",
            generation_id=generation_id,
            node_name="Node",
            node_runtime_fingerprint="runtime:test",
            output_names=("output",),
            dataframe_output_names=("output",),
            non_dataframe_outputs={},
            metadata={"output": {}},
            execution_order=DataFrameExecutionOrder(queued_at_us=1, task_id=generation_id),
        )

    await object_store.put("df:project-2:node-foreign:active", {"keep": True})
    assert await provider.data_blob_store.keys("df:project-1:node-1:")

    result = await facade.clear_data_cache(project_id="project-1", node_ids=["node-1"])

    assert result.cleared_keys
    assert await provider.data_blob_store.keys("df:project-1:node-1:") == []
    assert await provider.data_blob_store.keys("df:project-2:") == [
        "df:project-2:node-foreign:active"
    ]


@pytest.mark.asyncio
async def test_facade_clear_metadata_cache_removes_cache_and_requests_refresh() -> None:
    provider = _build_provider()
    facade = provider.create_facade()

    await facade.put_metadata_entry(
        project_id="project-1",
        node_id="node-1",
        cache_key="meta-cache-1",
        outputs={"output": {"value": 1}},
        metadata={"output": {"kind": "meta"}},
        meta_key_id="meta-key-1",
    )

    result = await facade.clear_metadata_cache(
        project_id="project-1",
        node_ids=["node-1"],
        send_metadata_task=True,
    )

    assert result.cleared_keys == ["meta-cache-1"]
    assert result.task_id == "task:project-1:node-1"
    assert await provider.metadata_blob_store.has("meta-cache-1") is False


@pytest.mark.asyncio
async def test_facade_get_dataframe_entry_paginates_cached_partitions() -> None:
    provider = _build_provider()
    facade = provider.create_facade()
    object_store = CodecObjectStore(provider.data_blob_store, provider.data_codec)
    cache = DataFrameExecutionCache(data_store=object_store)
    generation_id = "generation-1"
    meta = pd.DataFrame({"value": pd.Series(dtype="int64")})
    await cache.begin_output_generation(
        project_id="project-1",
        node_id="node-1",
        output_name="output",
        generation_id=generation_id,
        node_runtime_fingerprint="runtime:test",
        meta=meta,
        npartitions=2,
        known_divisions=False,
        divisions=None,
    )
    descriptors = []
    for part_no, part_df in enumerate(
        (pd.DataFrame({"value": [1, 2]}), pd.DataFrame({"value": [3, 4]}))
    ):
        descriptors.append(
            await cache.put_encoded_partition(
                project_id="project-1",
                node_id="node-1",
                output_name="output",
                generation_id=generation_id,
                part_no=part_no,
                rows=len(part_df),
                payload=cache.encode_partition(part_df),
            )
        )
    await cache.commit_output_generation(
        project_id="project-1",
        node_id="node-1",
        output_name="output",
        generation_id=generation_id,
        partitions=tuple(descriptors),
    )
    await cache.stage_execution_snapshot(
        project_id="project-1",
        node_id="node-1",
        generation_id=generation_id,
        node_name="Node",
        node_runtime_fingerprint="runtime:test",
        output_names=("output",),
        dataframe_output_names=("output",),
        non_dataframe_outputs={},
        metadata={"output": {}},
        execution_order=DataFrameExecutionOrder(queued_at_us=1, task_id=generation_id),
    )
    assert await object_store.has(dataframe_active_key(project_id="project-1", node_id="node-1"))

    result = await facade.get_dataframe_entry(
        project_id="project-1",
        node_id="node-1",
        output_name="output",
        offset=1,
        limit=2,
    )

    assert result.total_rows == 4
    assert result.total_partitions == 2
    assert result.dataframe["value"].tolist() == [2, 3]


@pytest.mark.asyncio
async def test_facade_get_json_entry_slices_list_payload_and_restore_metadata_normalizes_shape() -> None:
    provider = _build_provider()
    facade = provider.create_facade()

    await facade.put_data_entry(
        cache_key="json-cache-1",
        value=[1, 2, 3, 4],
        index_entries=[
            (
                JSONKey(project_id="project-1", node_id="node-1", output_name="output"),
                DataIndexEntry(cache_key="json-cache-1", output_name="output"),
            )
        ],
    )
    await facade.put_metadata_entry(
        project_id="project-1",
        node_id="node-1",
        cache_key="meta-cache-1",
        outputs={"output": {"value": "cached"}},
        metadata={},
        meta_key_id="meta-key-1",
    )

    json_result = await facade.get_json_entry(
        project_id="project-1",
        node_id="node-1",
        output_name="output",
        offset=1,
        limit=2,
    )
    restore_result = await facade.restore_metadata_entry(
        meta_cache_key="meta-cache-1",
        expected_output_names=["output", "signal_out"],
    )

    assert json_result.data == [2, 3]
    assert json_result.total_items == 4
    assert restore_result.restored is False

    await provider.metadata_index_store.put(
        MetaKey(project_id="project-1", node_id="node-1", meta_key_id="meta-key-2"),
        "meta-cache-2",
        ttl=facade.resolve_ttl(None),
    )
    await provider.metadata_blob_store.put(
        "meta-cache-2",
        provider.encode_metadata(
            MetadataCacheEntry(
                outputs={"output": {"value": "cached"}, "signal_out": {"value": True}},
                metadata={"output": {"kind": "meta"}},
            )
        ),
        ttl=facade.resolve_ttl(None),
    )

    restore_result = await facade.restore_metadata_entry(
        meta_cache_key="meta-cache-2",
        expected_output_names=["output", "signal_out"],
    )

    assert restore_result.restored is True
    assert restore_result.entry is not None
    assert restore_result.entry.metadata == {"output": {"kind": "meta"}, "signal_out": None}


@pytest.mark.asyncio
async def test_in_memory_index_store_keys_filters_by_requested_key_type() -> None:
    provider = _build_provider()
    facade = provider.create_facade()

    await facade.put_data_entry(
        cache_key="part-1",
        value=pd.DataFrame({"value": [1]}),
        index_entries=[
            (
                PDFKey(project_id="project-1", node_id="node-1", output_name="output", part_no=1),
                PDFIndexEntry(
                    cache_key="part-1",
                    output_name="output",
                    part_no=1,
                    total_parts=1,
                    rows=1,
                ),
            )
        ],
    )
    json_key = JSONKey(project_id="project-2", node_id="node-2", output_name="json")
    await facade.put_data_entry(
        cache_key="json-1",
        value={"ok": True},
        index_entries=[(json_key, DataIndexEntry(cache_key="json-1", output_name="json"))],
    )

    keys = await provider.data_index_store.keys(JSONKey)

    assert keys == [json_key]


def test_provider_create_facade_returns_recommended_entrypoint() -> None:
    provider = _build_provider()

    facade = provider.create_facade()

    assert isinstance(facade, PipelineCacheFacade)
    assert facade.provider is provider
