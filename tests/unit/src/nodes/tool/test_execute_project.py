from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import dask.dataframe as dd
import pandas as pd
import pytest

from src.modules.task_execution.domain.types import TaskExecutionStatus
from src.node_dsl import IO, NodeValidationError
from src.node_dsl.variables import VariableOutput
from src.nodes.tool import execute_project as execute_project_module
from src.nodes.tool.execute_project import ExecuteProject
from src.pipeline.execution_mode import PipelineExecutionMode


@pytest.mark.asyncio
async def test_execute_project_process_enqueues_without_wait(monkeypatch):
    enqueue_calls = []
    wait_calls = []

    async def fake_enqueue_project_task_for_node(**kwargs):
        enqueue_calls.append(kwargs)
        return SimpleNamespace(task_id="child-task-1")

    async def fake_wait_for_task_terminal_state(**kwargs):
        wait_calls.append(kwargs)

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

    node = ExecuteProject(
        user_id="user-1",
        project_id="parent-project-1",
        task_id="parent-task-1",
        node_id="node-1",
        target_project_id="child-project-1",
        target_project_name="Child Project",
        wait_for_completion=False,
    )

    await node.process()

    assert len(enqueue_calls) == 1
    assert enqueue_calls[0]["target_project_id"] == "child-project-1"
    assert wait_calls == []
    assert node.signal_out is True


@pytest.mark.asyncio
async def test_execute_project_accepts_display_name_without_affecting_execution(monkeypatch):
    enqueue_calls = []

    async def fake_enqueue_project_task_for_node(**kwargs):
        enqueue_calls.append(kwargs)
        return SimpleNamespace(task_id="child-task-1")

    monkeypatch.setattr(
        execute_project_module,
        "enqueue_project_task_for_node",
        fake_enqueue_project_task_for_node,
    )

    node = ExecuteProject(
        user_id="user-1",
        project_id="parent-project-1",
        task_id="parent-task-1",
        node_id="node-1",
        target_project_id="child-project-1",
        target_project_name="Renamed Child Project",
        wait_for_completion=False,
    )

    await node.process()

    assert node.target_project_name == "Renamed Child Project"
    assert enqueue_calls == [
        {
            "actor_user_id": "user-1",
            "target_project_id": "child-project-1",
            "parent_project_id": "parent-project-1",
            "parent_task_id": "parent-task-1",
            "wait_for_completion": False,
            "force_exec": True,
            "variables": {},
            "unresolved_variables_policy": "error",
            "system_variables_policy": "include",
        }
    ]


@pytest.mark.asyncio
async def test_execute_project_process_waits_for_child_when_enabled(monkeypatch):
    wait_calls = []

    async def fake_enqueue_project_task_for_node(**kwargs):
        return SimpleNamespace(task_id="child-task-1")

    async def fake_wait_for_task_terminal_state(**kwargs):
        wait_calls.append(kwargs)

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
    node = ExecuteProject(
        user_id="user-1",
        project_id="parent-project-1",
        task_id="parent-task-1",
        node_id="node-1",
        target_project_id="child-project-1",
        wait_for_completion=True,
        timeout_sec=15,
        cancel_on_timeout=True,
    )

    await node.process()

    assert wait_calls == [
        {
            "child_task_id": "child-task-1",
            "timeout_sec": 15,
            "cancel_on_timeout": True,
        }
    ]
    assert node.signal_out is True


@pytest.mark.asyncio
async def test_execute_project_process_requires_target_project_id():
    node = ExecuteProject(
        user_id="user-1",
        project_id="parent-project-1",
        task_id="parent-task-1",
        node_id="node-1",
        target_project_id="   ",
        wait_for_completion=False,
    )

    with pytest.raises(ValueError, match="target_project_id is empty"):
        await node.process()


@pytest.mark.asyncio
async def test_execute_project_runs_dataframe_rows_sequentially(monkeypatch):
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

    variables_pdf = pd.DataFrame(
        {
            "batch_size": pd.Series([10, pd.NA], dtype="Int64"),
            "run_at": pd.to_datetime(["2026-08-18T10:15:00", None]),
        }
    )
    node = ExecuteProject(
        user_id="user-1",
        project_id="parent-project-1",
        task_id="parent-task-1",
        node_id="node-1",
        target_project_id="child-project-1",
        wait_for_completion=True,
        timeout_sec=15,
        cancel_on_timeout=True,
        input_variables={
            "batch_size": VariableOutput(name="batch_size", type=IO.INT, value=100),
            "common": VariableOutput(name="common", type=IO.STRING, value="shared"),
        },
        variables_df=dd.from_pandas(variables_pdf, npartitions=1),
    )

    await node.process()

    assert events == [
        "enqueue:child-task-1",
        "wait:child-task-1",
        "enqueue:child-task-2",
        "wait:child-task-2",
    ]
    assert [call["variables"] for call in enqueue_calls] == [
        {
            "batch_size": VariableOutput(
                name="batch_size",
                type=IO.INT,
                value=10,
            ),
            "common": VariableOutput(
                name="common",
                type=IO.STRING,
                value="shared",
            ),
            "run_at": VariableOutput(
                name="run_at",
                type=IO.DATETIME,
                value=datetime(2026, 8, 18, 10, 15),
            ),
        },
        {
            "batch_size": VariableOutput(
                name="batch_size",
                type=IO.INT,
                value=None,
            ),
            "common": VariableOutput(
                name="common",
                type=IO.STRING,
                value="shared",
            ),
            "run_at": VariableOutput(
                name="run_at",
                type=IO.DATETIME,
                value=None,
            ),
        },
    ]
    assert wait_calls == [
        {
            "child_task_id": "child-task-1",
            "timeout_sec": 15,
            "cancel_on_timeout": True,
        },
        {
            "child_task_id": "child-task-2",
            "timeout_sec": 15,
            "cancel_on_timeout": True,
        },
    ]
    assert node.signal_out is True


@pytest.mark.asyncio
async def test_execute_project_requires_wait_for_dataframe_mode():
    node = ExecuteProject(
        user_id="user-1",
        project_id="parent-project-1",
        task_id="parent-task-1",
        node_id="node-1",
        target_project_id="child-project-1",
        wait_for_completion=False,
        variables_df=dd.from_pandas(pd.DataFrame({"batch_size": [10]}), npartitions=1),
    )

    with pytest.raises(NodeValidationError, match="requires `wait_for_completion=true`"):
        await node.validate()
    with pytest.raises(NodeValidationError, match="requires `wait_for_completion=true`"):
        await node.process()


@pytest.mark.asyncio
async def test_execute_project_empty_dataframe_completes_without_launch(monkeypatch):
    enqueue_calls = []

    async def fake_enqueue_project_task_for_node(**kwargs):
        enqueue_calls.append(kwargs)
        return SimpleNamespace(task_id="unexpected-child-task")

    monkeypatch.setattr(
        execute_project_module,
        "enqueue_project_task_for_node",
        fake_enqueue_project_task_for_node,
    )
    node = ExecuteProject(
        user_id="user-1",
        project_id="parent-project-1",
        task_id="parent-task-1",
        node_id="node-1",
        target_project_id="child-project-1",
        wait_for_completion=True,
        variables_df=dd.from_pandas(
            pd.DataFrame({"batch_size": pd.Series([], dtype="Int64")}),
            npartitions=1,
        ),
    )

    await node.process()

    assert enqueue_calls == []
    assert node.signal_out is True


@pytest.mark.asyncio
async def test_execute_project_stops_after_dataframe_iteration_failure(monkeypatch):
    enqueue_calls = []
    wait_calls = []

    async def fake_enqueue_project_task_for_node(**kwargs):
        enqueue_calls.append(kwargs)
        return SimpleNamespace(task_id=f"child-task-{len(enqueue_calls)}")

    async def fake_wait_for_task_terminal_state(**kwargs):
        wait_calls.append(kwargs)
        raise RuntimeError("child failed")

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
    node = ExecuteProject(
        user_id="user-1",
        project_id="parent-project-1",
        task_id="parent-task-1",
        node_id="node-1",
        target_project_id="child-project-1",
        wait_for_completion=True,
        variables_df=dd.from_pandas(pd.DataFrame({"batch_size": [10, 20]}), npartitions=1),
    )

    with pytest.raises(RuntimeError, match="child failed"):
        await node.process()

    assert len(enqueue_calls) == 1
    assert len(wait_calls) == 1
    assert node.signal_out is not True


def test_execute_project_rejects_invalid_dataframe_columns():
    with pytest.raises(NodeValidationError, match="non-empty strings"):
        ExecuteProject._validate_dataframe_columns(["valid", 123])

    with pytest.raises(NodeValidationError, match="must be unique"):
        ExecuteProject._validate_dataframe_columns(["batch_size", "batch_size"])


@pytest.mark.asyncio
async def test_execute_project_metadata_mode_does_not_compute_dataframe():
    class ExplodingDataFrame:
        @property
        def columns(self):
            return ["batch_size"]

        def compute(self):
            raise AssertionError("metadata mode must not compute variables_df")

    node = ExecuteProject(
        user_id="user-1",
        project_id="parent-project-1",
        task_id="parent-task-1",
        node_id="node-1",
        target_project_id="child-project-1",
        wait_for_completion=True,
        variables_df=ExplodingDataFrame(),
        execution_mode=PipelineExecutionMode.METADATA_ONLY,
    )

    await node.process()

    assert node.signal_out is True
