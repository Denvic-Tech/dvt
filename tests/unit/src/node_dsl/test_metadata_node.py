import pytest

from src.node_dsl import JSONOutputBaseNode, OutputField, IO
from src.node_dsl import BaseNode, InputField
from src.node_dsl.variables import VariableOutput, UnresolvedValue


class DummyJSONNode(JSONOutputBaseNode):
    output: IO.JSON = OutputField()

    def process(self) -> None:
        self.output = {"foo": "bar"}


class AsyncMetadataJSONNode(JSONOutputBaseNode):
    output: IO.JSON = OutputField()
    infer_metadata_calls = 0

    def process(self) -> None:
        self.output = {"foo": "bar"}

    async def infer_metadata(self):
        type(self).infer_metadata_calls += 1
        return {"output": {"kind": "async-json"}}


class VariableMetadataNode(BaseNode):
    variable_name: str = InputField(default="message")
    output_variable: IO.VARIABLE = OutputField()

    def process(self) -> None:
        self.output_variable = VariableOutput(
            name=self.variable_name,
            type=IO.STRING,
            value=UnresolvedValue(reason="metadata-only", declared_type="STRING"),
            var_type="user",
        )


async def test_metadata_includes_non_signal_outputs():
    node = DummyJSONNode(
        user_id="user-id",
        project_id="project-id",
        task_id="task-id",
        node_id="node-id",
    )

    node.process()

    resolved_metadata = await node.resolve_metadata()
    assert "signal_out" not in resolved_metadata
    assert "signal_error" not in resolved_metadata
    assert "output" in resolved_metadata
    assert resolved_metadata["output"] is not None
    assert str(resolved_metadata["output"].type) == "JSON"


@pytest.mark.asyncio
async def test_resolve_metadata_supports_sync_nodes():
    node = DummyJSONNode(
        user_id="user-id",
        project_id="project-id",
        task_id="task-id",
        node_id="node-id",
    )

    node.process()

    resolved_metadata = await node.resolve_metadata()

    assert "signal_out" not in resolved_metadata
    assert "signal_error" not in resolved_metadata
    assert "output" in resolved_metadata
    assert resolved_metadata["output"] is not None
    assert str(resolved_metadata["output"].type) == "JSON"


@pytest.mark.asyncio
async def test_resolve_metadata_supports_async_nodes_and_caches_result():
    AsyncMetadataJSONNode.infer_metadata_calls = 0
    node = AsyncMetadataJSONNode(
        user_id="user-id",
        project_id="project-id",
        task_id="task-id",
        node_id="node-id",
    )

    node.process()

    first_metadata = await node.resolve_metadata()
    second_metadata = await node.resolve_metadata()

    assert first_metadata == {"output": {"kind": "async-json"}}
    assert second_metadata == first_metadata
    assert AsyncMetadataJSONNode.infer_metadata_calls == 1


async def test_metadata_builds_variable_map_for_variable_outputs() -> None:
    node = VariableMetadataNode(
        user_id="user-id",
        project_id="project-id",
        task_id="task-id",
        node_id="node-id",
    )

    node.process()

    resolved_metadata = await node.resolve_metadata()

    assert resolved_metadata["output_variable"] is not None
    assert resolved_metadata["output_variable"].type == "VARIABLE_MAP"
    assert resolved_metadata["output_variable"].variables[0].name == "message"
    assert resolved_metadata["output_variable"].variables[0].value_state == "unresolved"
