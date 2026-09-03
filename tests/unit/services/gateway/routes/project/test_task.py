from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from services.gateway.routes.impl import task as task_impl
from services.gateway.routes.project import task as project_task

from src.pipeline.execution_mode import PipelineExecutionMode
from src.schemas.http.task import TaskCreateRequest, TaskResponse


@pytest.mark.asyncio
async def test_create_task_passes_runtime_variables_for_project_route(
    test_admin_user,
    test_admin_project,
):
    with patch.object(task_impl, "create_task_route_impl", new_callable=AsyncMock) as mock_impl:
        mock_impl.return_value = TaskResponse(
            success=True,
            message="Task queued.",
            task_id="task-123",
        )

        response = await project_task.create_task(
            session=AsyncMock(),
            user=test_admin_user,
            project=test_admin_project,
            payload=TaskCreateRequest(
                variables={
                    "shared": {"type": "STRING", "value": "request-override"},
                }
            ),
            mode=PipelineExecutionMode.FULL,
            force_exec=False,
            target_nodes=["node-1"],
        )

    assert response == mock_impl.return_value
    variables = mock_impl.call_args.kwargs["variables"]
    assert variables is not None
    assert variables["shared"].model_dump(mode="json") == {
        "type": "STRING",
        "value": "request-override",
        "is_list_type": False,
    }
    assert mock_impl.call_args.kwargs["target_nodes"] == ["node-1"]
