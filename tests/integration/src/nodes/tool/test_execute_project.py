from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from src import enums
from src.modules.task_execution.domain.types import TaskExecutionStatus, TaskSource
from src.node_dsl import IO
from src.node_dsl.core.input_values import NodeInputConstantValue, NodeInputLinkValue
from src.node_dsl.variables import VariableOutput
from src.nodes.tool.execute_project import node as execute_project_module
from src.pipeline.execution_mode import PipelineExecutionMode
from src.pipeline.processor import PipelineProcessor
from src.schemas.internal import NodeData, ProjectSettings, ProjectVariables, TaskInternal

pytestmark = pytest.mark.asyncio

DEFAULT_PROJECT_SETTINGS = ProjectSettings(
    store_enabled=True,
    ttl_time=10 * 60,
    workers_count=1,
)


def _build_task(
    *,
    wait_for_completion: bool,
    cancel_on_timeout: bool = False,
    unresolved_variables_policy: str = "error",
    system_variables_policy: str = "error",
    include_input_variable: bool = False,
    include_variables_df: bool = False,
) -> TaskInternal:
    execute_project_inputs = {
        "target_project_id": NodeInputConstantValue(value="child-project-1"),
        "target_project_name": NodeInputConstantValue(value="Child Project"),
        "wait_for_completion": NodeInputConstantValue(value=wait_for_completion),
        "timeout_sec": NodeInputConstantValue(value=15 if wait_for_completion else None),
        "cancel_on_timeout": NodeInputConstantValue(value=cancel_on_timeout),
        "unresolved_variables_policy": NodeInputConstantValue(value=unresolved_variables_policy),
        "system_variables_policy": NodeInputConstantValue(value=system_variables_policy),
    }
    pipeline = {}
    if include_variables_df:
        pipeline["variables_df"] = NodeData(
            name="JsonToDataFrame",
            inputs={
                "json": NodeInputConstantValue(
                    value=[
                        {"batch_size": 10, "region": "north"},
                        {"batch_size": 20, "region": "south"},
                    ]
                ),
                "orient": NodeInputConstantValue(value="columns"),
            },
        )
        execute_project_inputs["variables_df"] = NodeInputLinkValue(
            node_id="variables_df",
            output_name="output",
        )

    if include_input_variable:
        pipeline["create_variable"] = NodeData(
            name="CreateVariable",
            inputs={
                "name": NodeInputConstantValue(value="batch_size"),
                "type": NodeInputConstantValue(value=IO.INT),
                "value": NodeInputConstantValue(value=100),
            },
        )
        execute_project_inputs["input_variables"] = NodeInputLinkValue(
            node_id="create_variable",
            output_name="output_variables",
        )

    pipeline["execute_project"] = NodeData(
        name="ExecuteProject",
        inputs=execute_project_inputs,
    )
    return TaskInternal(
        project_id="parent-project-1",
        task_id="parent-task-1",
        user_id="user-1",
        organization_id="org-1",
        pipeline=pipeline,
        target_nodes=["execute_project"],
        mode=PipelineExecutionMode.FULL,
        send_ws_messages=False,
        source=TaskSource.NODE,
        retry_count=0,
        force_exec=True,
        project_settings=DEFAULT_PROJECT_SETTINGS,
        project_variables=ProjectVariables(),
        license_type=None,
        extension_names=[],
    )


async def test_execute_project_pipeline_unwraps_nested_future_from_enqueue(monkeypatch):
    enqueue_calls = []
    enqueue_started = asyncio.Event()
    child_task_future = asyncio.get_running_loop().create_future()

    async def fake_enqueue_project_task_for_node(**kwargs):
        enqueue_calls.append(kwargs)
        enqueue_started.set()
        return child_task_future

    monkeypatch.setattr(
        execute_project_module,
        "enqueue_project_task_for_node",
        fake_enqueue_project_task_for_node,
    )

    processor = PipelineProcessor(
        task=_build_task(wait_for_completion=False, include_input_variable=True)
    )

    process_task = asyncio.create_task(processor.process())
    await asyncio.wait_for(enqueue_started.wait(), timeout=5)

    assert enqueue_calls == [
        {
            "actor_user_id": "user-1",
            "target_project_id": "child-project-1",
            "parent_project_id": "parent-project-1",
            "parent_task_id": "parent-task-1",
            "wait_for_completion": False,
            "force_exec": True,
            "variables": {
                "batch_size": VariableOutput(
                    name="batch_size",
                    type=IO.INT,
                    value=100,
                )
            },
            "unresolved_variables_policy": "error",
            "system_variables_policy": "error",
        }
    ]
    assert not process_task.done()

    child_task_future.set_result(SimpleNamespace(task_id="child-task-1"))

    result = await asyncio.wait_for(process_task, timeout=5)

    assert result.success is True
    assert processor.nodes_outputs["execute_project"]["signal_out"].value is True
    assert processor.failed_nodes == []


async def test_execute_project_pipeline_waits_for_nested_future_from_wait_helper(monkeypatch):
    enqueue_calls = []
    wait_calls = []
    loop = asyncio.get_running_loop()
    child_task_future = loop.create_future()
    wait_future = loop.create_future()

    async def fake_enqueue_project_task_for_node(**kwargs):
        enqueue_calls.append(kwargs)
        return child_task_future

    async def fake_wait_for_task_terminal_state(**kwargs):
        wait_calls.append(kwargs)
        return wait_future

    monkeypatch.setattr(
        execute_project_module,
        "enqueue_project_task_for_node",
        fake_enqueue_project_task_for_node,
    )
    monkeypatch.setattr(
        execute_project_module,
        "wait_for_task_terminal_state",
        fake_wait_for_task_terminal_state,
    )

    processor = PipelineProcessor(
        task=_build_task(
            wait_for_completion=True,
            cancel_on_timeout=True,
            unresolved_variables_policy="skip",
            system_variables_policy="include",
        )
    )

    process_task = asyncio.create_task(processor.process())
    await asyncio.sleep(0)

    assert enqueue_calls == [
        {
            "actor_user_id": "user-1",
            "target_project_id": "child-project-1",
            "parent_project_id": "parent-project-1",
            "parent_task_id": "parent-task-1",
            "wait_for_completion": True,
            "force_exec": True,
            "variables": {},
            "unresolved_variables_policy": "skip",
            "system_variables_policy": "include",
        }
    ]
    assert not process_task.done()

    child_task_future.set_result(SimpleNamespace(task_id="child-task-1"))
    await asyncio.sleep(0)

    assert wait_calls == [
        {
            "child_task_id": "child-task-1",
            "timeout_sec": 15,
            "cancel_on_timeout": True,
        }
    ]
    assert not process_task.done()

    wait_future.set_result(TaskExecutionStatus.SUCCESS)

    result = await asyncio.wait_for(process_task, timeout=5)

    assert result.success is True
    assert processor.nodes_outputs["execute_project"]["signal_out"].value is True
    assert processor.failed_nodes == []


async def test_execute_project_pipeline_runs_dataframe_rows_sequentially(monkeypatch):
    enqueue_calls = []
    wait_calls = []
    events = []

    async def fake_enqueue_project_task_for_node(**kwargs):
        enqueue_calls.append(kwargs)
        child_task_id = f"child-task-{len(enqueue_calls)}"
        events.append(f"enqueue:{child_task_id}")
        return SimpleNamespace(task_id=child_task_id)

    async def fake_wait_for_task_terminal_state(**kwargs):
        wait_calls.append(kwargs)
        events.append(f"wait:{kwargs['child_task_id']}")
        return TaskExecutionStatus.SUCCESS

    monkeypatch.setattr(
        execute_project_module,
        "enqueue_project_task_for_node",
        fake_enqueue_project_task_for_node,
    )
    monkeypatch.setattr(
        execute_project_module,
        "wait_for_task_terminal_state",
        fake_wait_for_task_terminal_state,
    )

    processor = PipelineProcessor(
        task=_build_task(
            wait_for_completion=True,
            include_input_variable=True,
            include_variables_df=True,
        )
    )

    result = await asyncio.wait_for(processor.process(), timeout=5)

    assert result.success is True
    assert events == [
        "enqueue:child-task-1",
        "wait:child-task-1",
        "enqueue:child-task-2",
        "wait:child-task-2",
    ]
    assert [call["variables"] for call in enqueue_calls] == [
        {
            "batch_size": VariableOutput(name="batch_size", type=IO.INT, value=10),
            "region": VariableOutput(name="region", type=IO.STRING, value="north"),
        },
        {
            "batch_size": VariableOutput(name="batch_size", type=IO.INT, value=20),
            "region": VariableOutput(name="region", type=IO.STRING, value="south"),
        },
    ]
    assert wait_calls == [
        {
            "child_task_id": "child-task-1",
            "timeout_sec": 15,
            "cancel_on_timeout": False,
        },
        {
            "child_task_id": "child-task-2",
            "timeout_sec": 15,
            "cancel_on_timeout": False,
        },
    ]
    assert processor.nodes_outputs["execute_project"]["signal_out"].value is True
    assert processor.failed_nodes == []
