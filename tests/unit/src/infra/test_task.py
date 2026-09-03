from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.infra import task as task_infra
from src.modules.project.infra.db_models import ProjectRecord
from src.modules.task_execution.domain.types import TaskSource
from src.pipeline.execution_mode import PipelineExecutionMode
from src.schemas.http.project_variable import ProjectVariableBase
from src.schemas.internal import NodeData


class _FakeSession:
    async def commit(self) -> None:
        return None


@pytest.mark.asyncio
async def test_build_pending_task_from_project_merges_runtime_variables(monkeypatch):
    project = ProjectRecord(
        id="project-1",
        name="Test project",
        user_id="owner-1",
        organization_id="org-1",
        store_enabled=False,
        ttl_time=0,
        workers_count=1,
        dirty_node_ids=["missing-node", "node-1"],
        graph_revision=7,
        variables={
            "shared": {"type": "STRING", "value": "from-project", "is_list_type": False},
            "project_only": {"type": "INT", "value": 3, "is_list_type": False},
        },
    )
    user = SimpleNamespace(id="user-1")
    session = _FakeSession()
    created_executions: list = []

    monkeypatch.setattr(
        task_infra,
        "get_access_scope",
        lambda _user: SimpleNamespace(organization_id="org-1", owner_user_id="owner-1"),
    )

    async def fake_get_graph_by(*_args, **_kwargs):
        return [], [], None

    async def fake_check_extensions_availability(_extension_names):
        return [], []

    async def fake_create_pending_execution(*, execution):
        created_executions.append(execution)
        return None

    monkeypatch.setattr(task_infra.graph_crud, "get_graph_by", fake_get_graph_by)
    monkeypatch.setattr(
        task_infra,
        "build_pipeline_from_graph",
        lambda **_kwargs: {"node-1": NodeData(name="CreateVariable", inputs={})},
    )
    monkeypatch.setattr(task_infra, "resolve_execution_target_nodes", lambda **_kwargs: ["node-1"])
    monkeypatch.setattr(
        task_infra,
        "build_task_lifecycle_commands",
        lambda: SimpleNamespace(
            create_pending_execution=SimpleNamespace(execute=fake_create_pending_execution)
        ),
    )
    monkeypatch.setattr(
        task_infra,
        "get_dependency_manager",
        lambda: SimpleNamespace(check_extensions_availability=fake_check_extensions_availability),
    )
    monkeypatch.setattr("src.utils.extensions.collect_extension_names", lambda _pipeline: [])

    task = await task_infra.build_pending_task_from_project(
        project=project,
        user=user,
        session=session,
        mode=PipelineExecutionMode.FULL,
        force_exec=False,
        source=TaskSource.API,
        variables={
            "shared": ProjectVariableBase(type="STRING", value="from-request"),
            "request_only": ProjectVariableBase(type="BOOLEAN", value=True),
        },
    )

    assert task.project_variables.raw_values == {
        "shared": "from-request",
        "project_only": 3,
        "request_only": True,
    }
    assert created_executions and created_executions[0].task_id == task.task_id
    assert created_executions[0].project_id == task.project_id
    assert task.changed_node_ids == ["node-1"]
    assert task.graph_revision == 7
    assert project.variables == {
        "shared": {"type": "STRING", "value": "from-project", "is_list_type": False},
        "project_only": {"type": "INT", "value": 3, "is_list_type": False},
    }

