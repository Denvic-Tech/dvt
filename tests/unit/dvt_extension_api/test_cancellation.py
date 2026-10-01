from threading import Event
from unittest.mock import AsyncMock

from dask import delayed
import pytest

from dvt_extension_api.v1.execution import CancellationToken, NodeExecutionCancelled, ExecMode
from dvt_extension_api.v1.node import BaseNode
from src.node_dsl.registry import nodes, definitions, hooks
from src.pipeline.processor import PipelineProcessor
from src.schemas.internal import NodeData, ProjectSettings, ProjectVariables, TaskInternal


def test_default_token_and_existing_node_constructor():
    class ExistingNode(BaseNode):
        def process(self):
            self.cancellation.raise_if_requested()

    node = ExistingNode(user_id="u", project_id="p", task_id="t", node_id="n")
    node.process()
    assert not node.cancellation.is_requested()
    assert not CancellationToken().is_requested()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["stop", "unrequested", "error_after_stop"])
async def test_threaded_delayed_stop_uses_authoritative_signal(failure):
    event = Event()

    class CancellationProbeNode(BaseNode):
        def process(self):
            token = self.cancellation

            def work():
                if failure != "unrequested":
                    event.set()
                if failure == "error_after_stop":
                    raise ValueError("real failure")
                if failure == "unrequested":
                    raise NodeExecutionCancelled("no task stop")
                token.raise_if_requested()

            delayed(work, pure=False)().compute(scheduler="threads")

    CancellationProbeNode.__name__ += failure
    nodes.add(CancellationProbeNode)
    definitions.build(CancellationProbeNode)
    hooks.build(CancellationProbeNode)
    cancelled, failed, node_failed, succeeded = [AsyncMock() for _ in range(4)]
    task = TaskInternal(
        project_id="p", user_id="u", task_id="t",
        pipeline={"n": NodeData(name=CancellationProbeNode.__name__, inputs={}, store_enabled=False)},
        mode=ExecMode.FULL,
        project_settings=ProjectSettings(store_enabled=False, ttl_time=600, workers_count=2),
        project_variables=ProjectVariables(variables={}), license_type="000",
    )
    result = await PipelineProcessor(
        task=task, stop_event=event, on_task_canceled=cancelled,
        on_task_error=failed, on_node_error=node_failed, on_task_success=succeeded,
    ).process()
    assert not result.success
    succeeded.assert_not_called()
    if failure == "stop":
        cancelled.assert_awaited_once()
        failed.assert_not_called()
        node_failed.assert_not_called()
        assert result.error_message is None
    else:
        cancelled.assert_not_called()
        failed.assert_awaited_once()
        node_failed.assert_awaited_once()
        assert result.error_message
