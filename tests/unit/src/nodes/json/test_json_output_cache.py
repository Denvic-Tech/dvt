import pytest

from src.modules.pipeline_cache import (
    CodecObjectStore,
    DataIndexEntry,
    DumpEngineCodec,
    InMemoryBlobStore,
    InMemoryIndexStore,
    JSONKey,
)
from src.node_dsl import IO, InputField, JSONOutputBaseNode, OutputField
from src.pipeline.execution_mode import PipelineExecutionMode


def _build_data_store():
    return CodecObjectStore(InMemoryBlobStore(default_ttl=600), DumpEngineCodec())


def _build_data_index_store():
    codec = DumpEngineCodec()
    return InMemoryIndexStore(
        serializer=codec.dump,
        deserializer=codec.load,
        default_ttl=600,
        separator=":::",
    )


class _JSONProducer(JSONOutputBaseNode):
    value: int = InputField()
    output: IO.JSON = OutputField()

    def process(self) -> None:
        self.output = {"value": self.value}


@pytest.mark.asyncio
async def test_json_output_is_cached_and_indexed_when_store_enabled() -> None:
    data_store = _build_data_store()
    data_index_store = _build_data_index_store()

    node = _JSONProducer(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="node-json",
        value=1,
        data_store=data_store,
        data_index_store=data_index_store,
        store_enabled=True,
    )

    await node.execute(PipelineExecutionMode.FULL)

    index_key = JSONKey(project_id="project", node_id="node-json", output_name="output")
    cached_entries = await data_index_store.query(index_key)
    assert cached_entries, "JSON output must be indexed"

    entry = cached_entries[0]
    assert isinstance(entry, DataIndexEntry)

    cached_value = await data_store.get(entry.cache_key)
    assert cached_value == {"value": 1}


@pytest.mark.asyncio
async def test_json_output_cache_is_cleaned_up_on_full_rerun() -> None:
    data_store = _build_data_store()
    data_index_store = _build_data_index_store()

    node1 = _JSONProducer(
        user_id="user",
        project_id="project",
        task_id="task-1",
        node_id="node-json",
        value=1,
        data_store=data_store,
        data_index_store=data_index_store,
        store_enabled=True,
    )
    await node1.execute(PipelineExecutionMode.FULL)

    index_key = JSONKey(project_id="project", node_id="node-json", output_name="output")
    cached_entries1 = await data_index_store.query(index_key)
    entry1 = cached_entries1[0]
    assert await data_store.has(entry1.cache_key)

    node2 = _JSONProducer(
        user_id="user",
        project_id="project",
        task_id="task-2",
        node_id="node-json",
        value=2,
        data_store=data_store,
        data_index_store=data_index_store,
        store_enabled=True,
    )
    await node2.execute(PipelineExecutionMode.FULL)

    assert not await data_store.has(entry1.cache_key), "Old JSON cache must be removed on rerun"

    cached_entries2 = await data_index_store.query(index_key)
    entry2 = cached_entries2[0]
    cached_value2 = await data_store.get(entry2.cache_key)
    assert cached_value2 == {"value": 2}
