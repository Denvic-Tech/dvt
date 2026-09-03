from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import ANY

import pytest

from src import enums
from src.infra import task_node_runtime
from src.modules.task_execution.domain.types import TaskExecutionStatus, TaskSource
from src.node_dsl.variables import VariableOutput, make_unresolved_value
from src.pipeline.execution_mode import PipelineExecutionMode
from src.schemas.http.project_variable import ProjectVariableBase
from src.schemas.internal import TaskInternal


class _FakeScalarResult:
    def __init__(self, value):
        self._value = value

    def first(self):
        return self._value


class _FakeAsyncSession:
    async def commit(self):
        return None


class _FakeAsyncSessionLocal:
    async def __aenter__(self):
        return _FakeAsyncSession()

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeOrchestrator:
    def __init__(self, snapshot=None):
        self.snapshot = snapshot
        self.cancelled_task_ids: list[str] = []

    async def get_execution_capacity(self):
        assert self.snapshot is not None
        return self.snapshot

    async def cancel_task(self, task_id: str) -> None:
        self.cancelled_task_ids.append(task_id)


class _FakeSharedClient:
    def __init__(self, client):
        self._client = client

    async def get(self):
        return self._client


@pytest.mark.asyncio
async def test_enqueue_project_task_for_node_loads_user_and_project(monkeypatch):
    monkeypatch.setattr(task_node_runtime, "AsyncSessionLocal", _FakeAsyncSessionLocal)

    actor_user = SimpleNamespace(id="user-1", organization_id="org-1", role="admin")
    target_project = SimpleNamespace(id="project-2")

    async def fake_get_users_by(*_args, **_kwargs):
        return _FakeScalarResult(actor_user)

    async def fake_get_projects_by(*_args, **_kwargs):
        return _FakeScalarResult(target_project)

    build_calls = []
    published_commands = []

    async def fake_build_pending_task_from_project(**kwargs):
        build_calls.append(kwargs)
        return TaskInternal.model_construct(
            task_id="child-task-1",
            user_id="user-1",
            organization_id="org-1",
            project_id="project-2",
            pipeline={},
            mode=PipelineExecutionMode.FULL,
            send_ws_messages=True,
            source=TaskSource.NODE,
            retry_count=0,
            force_exec=True,
            project_settings=None,
            project_variables=None,
            license_type=None,
            extension_names=[],
            outputs_to_execute=None,
        )

    async def fake_publish_orchestrator_command(command):
        published_commands.append(command)

    monkeypatch.setattr(task_node_runtime.user_crud, "get_users_by", fake_get_users_by)
    monkeypatch.setattr(task_node_runtime.project_crud, "get_projects_by", fake_get_projects_by)
    monkeypatch.setattr("src.infra.task.build_pending_task_from_project", fake_build_pending_task_from_project)
    monkeypatch.setattr(task_node_runtime, "publish_orchestrator_command", fake_publish_orchestrator_command)
    monkeypatch.setattr("src.utils.worker_id.get_worker_id", lambda: "worker-1")

    task = await task_node_runtime.enqueue_project_task_for_node(
        actor_user_id="user-1",
        target_project_id="project-2",
        parent_project_id="project-1",
        parent_task_id="parent-task-1",
        wait_for_completion=False,
        force_exec=True,
        variables={
            "batch_size": VariableOutput(
                name="batch_size",
                type="INT",
                value=100,
            )
        },
    )

    assert task.task_id == "child-task-1"
    assert build_calls == [{
        "project": target_project,
        "send_ws_messages": True,
        "force_exec": True,
        "variables": {
            "batch_size": ProjectVariableBase(type="INT", value=100),
        },
        "source": TaskSource.NODE,
        "user": actor_user,
        "session": ANY,
    }]
    assert len(published_commands) == 1
    assert published_commands[0].task.task_id == "child-task-1"
    assert published_commands[0].origin_worker_id == "worker-1"
    assert published_commands[0].parent_project_id == "project-1"
    assert published_commands[0].wait_for_completion is False


def test_build_nested_task_variable_overrides_includes_system_variables() -> None:
    overrides = task_node_runtime._build_nested_task_variable_overrides(
        {
            "user_value": VariableOutput(
                name="user_value",
                type="STRING",
                value="value",
            ),
            "system_value": VariableOutput(
                name="system_value",
                type="BOOLEAN",
                value=True,
                var_type="system",
            ),
        },
        unresolved_variables_policy="error",
        system_variables_policy="include",
    )

    assert overrides == {
        "user_value": ProjectVariableBase(type="STRING", value="value"),
        "system_value": ProjectVariableBase(type="BOOLEAN", value=True),
    }


def test_build_nested_task_variable_overrides_skips_by_policy() -> None:
    overrides = task_node_runtime._build_nested_task_variable_overrides(
        {
            "pending": VariableOutput(
                name="pending",
                type="STRING",
                value=make_unresolved_value(reason="metadata only", declared_type="STRING"),
            ),
            "system_value": VariableOutput(
                name="system_value",
                type="BOOLEAN",
                value=True,
                var_type="system",
            ),
        },
        unresolved_variables_policy="skip",
        system_variables_policy="skip",
    )

    assert overrides is None


@pytest.mark.parametrize(
    ("variables", "unresolved_policy", "system_policy", "expected_message"),
    [
        (
            {
                "pending": VariableOutput(
                    name="pending",
                    type="STRING",
                    value=make_unresolved_value(
                        reason="metadata only",
                        declared_type="STRING",
                    ),
                )
            },
            "error",
            "skip",
            "Cannot pass unresolved variable 'pending'",
        ),
        (
            {
                "system_value": VariableOutput(
                    name="system_value",
                    type="BOOLEAN",
                    value=True,
                    var_type="system",
                )
            },
            "skip",
            "error",
            "Cannot pass system variable 'system_value'",
        ),
    ],
)
def test_build_nested_task_variable_overrides_errors_by_policy(
    variables,
    unresolved_policy,
    system_policy,
    expected_message,
) -> None:
    with pytest.raises(ValueError, match=expected_message):
        task_node_runtime._build_nested_task_variable_overrides(
            variables,
            unresolved_variables_policy=unresolved_policy,
            system_variables_policy=system_policy,
        )


@pytest.mark.asyncio
async def test_enqueue_project_task_for_node_marks_child_error_when_publish_fails(monkeypatch):
    monkeypatch.setattr(task_node_runtime, "AsyncSessionLocal", _FakeAsyncSessionLocal)

    actor_user = SimpleNamespace(id="user-1", organization_id="org-1", role="admin")
    target_project = SimpleNamespace(id="project-2")
    mark_error_calls = []

    async def fake_get_users_by(*_args, **_kwargs):
        return _FakeScalarResult(actor_user)

    async def fake_get_projects_by(*_args, **_kwargs):
        return _FakeScalarResult(target_project)

    async def fake_build_pending_task_from_project(**_kwargs):
        return TaskInternal.model_construct(
            task_id="child-task-1",
            user_id="user-1",
            organization_id="org-1",
            project_id="project-2",
            pipeline={},
            mode=PipelineExecutionMode.FULL,
            send_ws_messages=True,
            source=TaskSource.NODE,
            retry_count=0,
            force_exec=True,
            project_settings=None,
            project_variables=None,
            license_type=None,
            extension_names=[],
            outputs_to_execute=None,
        )

    async def fake_publish_orchestrator_command(_command):
        raise RuntimeError("stream unavailable")

    async def fake_fail_pending(*_args, **kwargs):
        mark_error_calls.append(kwargs)
        return None

    monkeypatch.setattr(task_node_runtime.user_crud, "get_users_by", fake_get_users_by)
    monkeypatch.setattr(task_node_runtime.project_crud, "get_projects_by", fake_get_projects_by)
    monkeypatch.setattr("src.infra.task.build_pending_task_from_project", fake_build_pending_task_from_project)
    monkeypatch.setattr(task_node_runtime, "publish_orchestrator_command", fake_publish_orchestrator_command)
    monkeypatch.setattr(
        task_node_runtime,
        "build_task_lifecycle_commands",
        lambda: SimpleNamespace(
            fail_pending_execution=SimpleNamespace(execute=fake_fail_pending)
        ),
    )
    monkeypatch.setattr("src.utils.worker_id.get_worker_id", lambda: "worker-1")

    with pytest.raises(RuntimeError, match="stream unavailable"):
        await task_node_runtime.enqueue_project_task_for_node(
            actor_user_id="user-1",
            target_project_id="project-2",
            parent_project_id="project-1",
            parent_task_id="parent-task-1",
            wait_for_completion=False,
            force_exec=True,
        )

    assert mark_error_calls == [{
        "task_id": "child-task-1",
        "message": "Failed nested task queue",
    }]


@pytest.mark.asyncio
async def test_wait_for_task_terminal_state_returns_success(monkeypatch):
    monkeypatch.setattr(task_node_runtime, "AsyncSessionLocal", _FakeAsyncSessionLocal)

    task_entry = SimpleNamespace(
        task_id="child-task-1",
        status=TaskExecutionStatus.SUCCESS,
        message=None,
        termination_reason=None,
    )

    async def fake_get_task_by_id(*_args, **_kwargs):
        return task_entry

    monkeypatch.setattr(task_node_runtime, "get_task_by_id", fake_get_task_by_id)

    status = await task_node_runtime.wait_for_task_terminal_state(
        child_task_id="child-task-1",
        poll_interval_sec=0.01,
        timeout_sec=1,
    )

    assert status == TaskExecutionStatus.SUCCESS


@pytest.mark.asyncio
async def test_wait_for_task_terminal_state_timeout_requests_cancel(monkeypatch):
    monkeypatch.setattr(task_node_runtime, "AsyncSessionLocal", _FakeAsyncSessionLocal)

    task_entry = SimpleNamespace(
        task_id="child-task-1",
        status=TaskExecutionStatus.RUNNING,
        message=None,
        termination_reason=None,
    )

    async def fake_get_task_by_id(*_args, **_kwargs):
        return task_entry

    fake_orchestrator = _FakeOrchestrator()

    async def fake_sleep(*_args, **_kwargs):
        return None

    monotonic_calls = {"count": 0}

    def fake_monotonic():
        monotonic_calls["count"] += 1
        if monotonic_calls["count"] == 1:
            return 0.0
        return 0.2

    monkeypatch.setattr(task_node_runtime, "get_task_by_id", fake_get_task_by_id)
    monkeypatch.setattr(task_node_runtime.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(task_node_runtime.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(
        task_node_runtime,
        "shared_orchestrator",
        _FakeSharedClient(fake_orchestrator),
    )

    with pytest.raises(TimeoutError, match="Timed out while waiting for child task"):
        await task_node_runtime.wait_for_task_terminal_state(
            child_task_id="child-task-1",
            poll_interval_sec=0.01,
            timeout_sec=0.1,
            cancel_on_timeout=True,
        )

    assert fake_orchestrator.cancelled_task_ids == ["child-task-1"]
