import pytest

import src.node_dsl.base_node.base as base_node_module
from src.node_dsl import IO, JSONOutputBaseNode, OutputField
from src.node_dsl.base_node.internal import InternalBaseNode
from src.pipeline.execution_mode import PipelineExecutionMode


class _SyncMetadataInternalNode(InternalBaseNode):
    output: IO.STRING = OutputField()
    process_calls = 0
    metadata_calls = 0

    def process(self) -> None:
        type(self).process_calls += 1
        raise AssertionError("process() should not be called in metadata mode")

    def process_metadata(self) -> None:
        type(self).metadata_calls += 1
        self.output = "metadata-sync"


class _AsyncMetadataJsonNode(JSONOutputBaseNode):
    output: IO.JSON = OutputField()
    process_calls = 0
    metadata_calls = 0

    def process(self) -> None:
        type(self).process_calls += 1
        raise AssertionError("process() should not be called in metadata mode")

    async def process_metadata(self) -> None:
        type(self).metadata_calls += 1
        self.output = {"status": "metadata-async"}


class _FallbackMetadataJsonNode(JSONOutputBaseNode):
    output: IO.JSON = OutputField()
    process_calls = 0

    def process(self) -> None:
        type(self).process_calls += 1
        self.output = {"status": "fallback"}


@pytest.mark.asyncio
async def test_execution_mixin_supports_sync_process_metadata() -> None:
    _SyncMetadataInternalNode.process_calls = 0
    _SyncMetadataInternalNode.metadata_calls = 0
    node = _SyncMetadataInternalNode(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="node",
    )

    await node.execute(PipelineExecutionMode.METADATA_ONLY)

    assert _SyncMetadataInternalNode.process_calls == 0
    assert _SyncMetadataInternalNode.metadata_calls == 1
    assert node.output == "metadata-sync"


@pytest.mark.asyncio
async def test_json_output_execute_supports_async_process_metadata() -> None:
    _AsyncMetadataJsonNode.process_calls = 0
    _AsyncMetadataJsonNode.metadata_calls = 0
    node = _AsyncMetadataJsonNode(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="node",
    )

    await node.execute(PipelineExecutionMode.METADATA_ONLY)

    assert _AsyncMetadataJsonNode.process_calls == 0
    assert _AsyncMetadataJsonNode.metadata_calls == 1
    assert node.output == {"status": "metadata-async"}


@pytest.mark.asyncio
async def test_base_node_process_metadata_logs_warning_and_falls_back(monkeypatch) -> None:
    _FallbackMetadataJsonNode.process_calls = 0
    warnings: list[str] = []

    def _fake_warning(message, *args, **kwargs) -> None:
        warnings.append(message.format(*args, **kwargs))

    monkeypatch.setattr(base_node_module.logger, "warning", _fake_warning)

    node = _FallbackMetadataJsonNode(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="node",
    )

    await node.execute(PipelineExecutionMode.METADATA_ONLY)

    assert _FallbackMetadataJsonNode.process_calls == 1
    assert node.output == {"status": "fallback"}
    assert warnings
    assert "process_metadata" in warnings[0]
