from types import SimpleNamespace

import pytest

from src.pipeline import processor as processor_module
from src.pipeline.execution_mode import PipelineExecutionMode
from src.pipeline.processor import PipelineProcessor


class _StopEvent:
    def __init__(self) -> None:
        self._set = False

    def is_set(self) -> bool:
        return self._set

    def set(self) -> None:
        self._set = True


@pytest.mark.asyncio
async def test_stop_during_current_node_prevents_next_node_start(monkeypatch):
    stop_event = _StopEvent()
    started: list[str] = []

    class _FakeNode:
        CACHABLE = False
        OUTPUT_NODE = False
        TTL_CACHE = 0

        def __init__(self, node_id: str) -> None:
            self.node_id = node_id

        @classmethod
        def from_pipeline_processor(cls, *, node_id: str, **_kwargs):
            return cls(node_id)

        async def validate(self) -> None:
            return None

        def get_metadata_cache_key(self):
            return None

        async def execute(self, *, mode) -> None:
            started.append(self.node_id)
            if self.node_id == "first":
                # Simulate cooperative STOP arriving while this node is running.
                stop_event.set()

        def get_outputs(self):
            return {}

        async def resolve_metadata(self):
            return {}

    fake_definition = SimpleNamespace(output_definitions={}, input_definitions={}, name="Fake")
    monkeypatch.setattr(processor_module, "topological_sort", lambda **_kwargs: ["first", "second"])
    monkeypatch.setattr(processor_module.registry, "get_node", lambda _name: _FakeNode)
    monkeypatch.setattr(processor_module.registry, "get_definition", lambda _name: fake_definition)

    task = SimpleNamespace(
        project_id="project",
        task_id="task",
        user_id="user",
        pipeline={
            "first": SimpleNamespace(name="Fake", inputs={}, store_enabled=False),
            "second": SimpleNamespace(name="Fake", inputs={}, store_enabled=False),
        },
        target_nodes=None,
        changed_node_ids=None,
        metadata_changed_node_ids=None,
        project_variables=None,
        mode=PipelineExecutionMode.FULL,
    )
    processor = PipelineProcessor(task=task, stop_event=stop_event)

    result = await processor.process()

    assert result.success is False
    assert started == ["first"]
    assert stop_event.is_set() is True
