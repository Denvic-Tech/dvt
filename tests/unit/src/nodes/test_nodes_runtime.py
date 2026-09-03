import pytest

from src.nodes.testing.simple_input import SimpleInputNode
from src.pipeline.execution_mode import PipelineExecutionMode


@pytest.mark.asyncio
async def test_simple_input_node_produces_processed_output():
    node = SimpleInputNode(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="node-input",
        value_in="hello",
    )

    await node.execute(PipelineExecutionMode.FULL)
    assert node.value_out == "Processed: hello"
