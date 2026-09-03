from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import status
from usrak.core.dependencies.user import get_optional_user_any

from services.gateway.deps import (
    project as project_deps,
)
from services.gateway.routes.impl import task as task_impl
from services.gateway.routes.public.project import task as project_crud

from src.enums import DVTDefaultRoles
from src.modules.project.infra.db_models import ProjectRecord
from src.modules.task_execution.domain.types import TaskExecutionStatus, TaskSource
from src.modules.user.infra.db_models import UserRecord
from src.pipeline.execution_mode import PipelineExecutionMode
from src.schemas.http.task import TaskCreateRequest, TaskInfo, TaskResponse


def _create_user(
    session,
    *,
    email: str,
    role: str,
    organization_id: str,
) -> UserRecord:
    user = UserRecord(
        email=email,
        hashed_password="hashed",
        auth_provider="email",
        is_verified=True,
        is_active=True,
        role=role,
        organization_id=organization_id,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@pytest.fixture
def mock_user(db_session, test_organization) -> UserRecord:
    return _create_user(
        db_session,
        email="superadmin@example.com",
        role=DVTDefaultRoles.SUPERADMIN.value,
        organization_id=test_organization.id,
    )


@pytest.fixture
def mock_project(test_organization):
    """Создает mock проекта"""
    project = MagicMock(spec=ProjectRecord)
    project.id = "test-project-id"
    project.name = "Test Project"
    project.organization_id = test_organization.id
    project.owner_id = "test-user-id"
    return project


@pytest.fixture
def mock_orchestrator_client():
    """Создает mock клиента оркестратора"""
    client = AsyncMock()
    client.cancel_task = AsyncMock()
    return client


@pytest.fixture
def set_current_user(gateway_client):
    from services.gateway.main import app

    def _set(user: UserRecord) -> None:
        app.dependency_overrides[project_deps.get_user_project_by_path_any_auth] = lambda: user
        app.dependency_overrides[get_optional_user_any] = lambda: user
        app.dependency_overrides[project_crud._get_user] = lambda: user

    return _set


@pytest.fixture
def set_current_project(gateway_client):
    """Фикстура для установки текущего проекта в зависимостях"""
    from services.gateway.main import app
    
    def _set(project: ProjectRecord) -> None:
        app.dependency_overrides[project_deps.get_user_project_by_path_any_auth] = lambda: project
        
    return _set


@pytest.mark.asyncio
async def test_create_task_success(
    gateway_client,
    router_prefix,
    set_current_user,
    set_current_project,
    mock_user,
    mock_project,
    db_session,
):
    """Тест успешного создания задачи"""
    set_current_user(mock_user)
    set_current_project(mock_project)
    
    mock_task_response = TaskResponse(
        task_id="task-123",
        status=TaskExecutionStatus.PENDING,
        source=TaskSource.API,
        created_at="2024-01-01T00:00:00",
        success=True,
        message="Task created",
    )
    
    with patch.object(task_impl, 'create_task_route_impl', new_callable=AsyncMock) as mock_impl:
        mock_impl.return_value = mock_task_response
        
        response = await gateway_client.post(
            f"{router_prefix}/public/projects/{mock_project.id}/tasks/new",
            params={
                "mode": PipelineExecutionMode.FULL,
                "force_exec": False,
                "target_nodes": "node-123",
            }
        )
        
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["task_id"] == "task-123"
        assert mock_impl.call_args.kwargs["target_nodes"] == ["node-123"]
        # mock_impl.assert_called_once_with(
        #     session=db_session,
        #     user=mock_user,
        #     project=mock_project,
        #     target_nodes=["node-123"],
        #     mode=PipelineExecutionMode.FULL,
        #     force_exec=False,
        #     source=TaskSource.API,
        # )


@pytest.mark.asyncio
async def test_create_task_with_default_params(
    gateway_client,
    router_prefix,
    set_current_user,
    set_current_project,
    mock_user,
    mock_project,
    db_session,
):
    """Тест создания задачи с параметрами по умолчанию"""
    set_current_user(mock_user)
    set_current_project(mock_project)
    
    mock_task_response = TaskResponse(
        task_id="task-123",
        status=TaskExecutionStatus.PENDING,
        source=TaskSource.API,
        created_at="2024-01-01T00:00:00",
        success=True,
        message="Task created",
    )
    
    with patch.object(task_impl, 'create_task_route_impl', new_callable=AsyncMock) as mock_impl:
        mock_impl.return_value = mock_task_response
        
        response = await gateway_client.post(f"{router_prefix}/public/projects/{mock_project.id}/tasks/new")
        
        assert response.status_code == status.HTTP_200_OK
        assert mock_impl.call_args.kwargs["target_nodes"] is None
        # mock_impl.assert_called_once_with(
        #     session=db_session,
        #     user=mock_user,
        #     project=mock_project,
        #     target_nodes=None,
        #     mode=PipelineExecutionMode.FULL,
        #     force_exec=False,
        #     source=TaskSource.API,
        # )


@pytest.mark.asyncio
async def test_create_task_passes_runtime_variables(
    mock_user,
    mock_project,
):
    mock_task_response = TaskResponse(
        success=True,
        message="Task created",
        task_id="task-123",
    )

    with patch.object(task_impl, "create_task_route_impl", new_callable=AsyncMock) as mock_impl:
        mock_impl.return_value = mock_task_response

        response = await project_crud.create_task(
            session=MagicMock(),
            user=mock_user,
            project=mock_project,
            payload=TaskCreateRequest(
                variables={
                    "shared": {"type": "STRING", "value": "request-override"},
                    "new_var": {"type": "INT", "value": 7},
                }
            ),
            mode=PipelineExecutionMode.FULL,
            force_exec=False,
            target_nodes=None,
        )

    assert response == mock_task_response
    variables = mock_impl.call_args.kwargs["variables"]
    assert variables is not None
    assert variables["shared"].model_dump(mode="json") == {
        "type": "STRING",
        "value": "request-override",
        "is_list_type": False,
    }
    assert variables["new_var"].model_dump(mode="json") == {
        "type": "INT",
        "value": 7,
        "is_list_type": False,
    }


@pytest.mark.asyncio
async def test_cancel_task_success(
    gateway_client,
    router_prefix,
    set_current_user,
    mock_user,
    mock_project,
    mock_orchestrator_client,
    db_session,
):
    """Тест успешной отмены задачи"""
    set_current_user(mock_user)
    
    mock_task_response = TaskResponse(
        task_id="task-123",
        status=TaskExecutionStatus.PENDING,
        source=TaskSource.API,
        created_at="2024-01-01T00:00:00",
        success=True,
        message="Task created",
    )
    
    with patch.object(task_impl, 'cancel_task_route_impl', new_callable=AsyncMock) as mock_impl:
        mock_impl.return_value = mock_task_response
        
        response = await gateway_client.post(
            f"{router_prefix}/public/projects/{mock_project.id}/tasks/task-123/cancel",
            params={"project_id": "project-123"}
        )
        
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["task_id"] == "task-123"
        # mock_impl.assert_called_once_with(
        #     project_id="project-123",
        #     task_id="task-123",
        #     session=db_session,
        #     user=mock_user,
        #     orchestrator=mock_orchestrator_client,
        # )


@pytest.mark.asyncio
async def test_cancel_task_not_found(
    gateway_client,
    router_prefix,
    set_current_user,
    mock_user,
    mock_project,
    mock_orchestrator_client,
    db_session,
):
    """Тест отмены несуществующей задачи"""
    set_current_user(mock_user)
    
    with patch.object(task_impl, 'cancel_task_route_impl', new_callable=AsyncMock) as mock_impl:
        from fastapi import HTTPException
        mock_impl.side_effect = HTTPException(status_code=404, detail="Task not found")
        
        response = await gateway_client.post(
            f"{router_prefix}/public/projects/{mock_project.id}/tasks/non-existent/cancel",
            params={"project_id": "project-123"}
        )
        
        assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_get_task_info_success(
    gateway_client,
    router_prefix,
    set_current_user,
    mock_project,
    mock_user,
    db_session,
):
    """Тест успешного получения информации о задаче"""
    set_current_user(mock_user)
    
    mock_task_info = TaskInfo(
        task_id="task-123",
        project_id="project-123",
        status=TaskExecutionStatus.RUNNING,  # Используйте enum, не строку
        source=TaskSource.API,
        progress=50,
        created_at="2024-01-01T00:00:00",
        updated_at="2024-01-01T00:01:00",
    )
    
    with patch.object(task_impl, 'get_task_info_route_impl', new_callable=AsyncMock) as mock_impl:
        mock_impl.return_value = mock_task_info
        
        response = await gateway_client.get(
            f"{router_prefix}/public/projects/{mock_project.id}/tasks/task-123/info",
            params={"project_id": "project-123"}
        )
        
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["task_id"] == "task-123"
        assert response.json()["status"] == TaskExecutionStatus.RUNNING.value
        # mock_impl.assert_called_once_with(
        #     project_id="project-123",
        #     task_id="task-123",
        #     session=db_session,
        #     user=mock_user,
        # )


@pytest.mark.asyncio
async def test_get_task_info_not_found(
    gateway_client,
    router_prefix,
    set_current_user,
    mock_project,
    mock_user,
    db_session,
):
    """Тест получения информации о несуществующей задаче"""
    set_current_user(mock_user)
    
    with patch.object(task_impl, 'get_task_info_route_impl', new_callable=AsyncMock) as mock_impl:
        from fastapi import HTTPException
        mock_impl.side_effect = HTTPException(status_code=404, detail="Task not found")
        
        response = await gateway_client.get(
            f"{router_prefix}/public/projects/{mock_project.id}/tasks/non-existent/info",
            params={"project_id": "project-123"}
        )
        
        assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_get_task_info_unauthorized_access(
    gateway_client,
    router_prefix,
    set_current_user,
    mock_project,
    mock_user,
    db_session,
):
    """Тест доступа к чужой задаче без прав"""
    set_current_user(mock_user)
    
    with patch.object(task_impl, 'get_task_info_route_impl', new_callable=AsyncMock) as mock_impl:
        from fastapi import HTTPException
        mock_impl.side_effect = HTTPException(status_code=403, detail="Access denied")
        
        response = await gateway_client.get(
            f"{router_prefix}/public/projects/{mock_project.id}/tasks/other-task/info",
            params={"project_id": "other-project"}
        )
        
        assert response.status_code in [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN]


@pytest.mark.asyncio
async def test_create_task_with_force_execution(
    gateway_client,
    router_prefix,
    set_current_user,
    set_current_project,
    mock_user,
    mock_project,
    db_session,
):
    """Тест создания задачи с принудительным выполнением"""
    set_current_user(mock_user)
    set_current_project(mock_project)
    
    mock_task_response = TaskResponse(
        task_id="task-123",
        status=TaskExecutionStatus.PENDING,
        source=TaskSource.API,
        created_at="2024-01-01T00:00:00",
        success=True,
        message="Task created",
    )
    
    with patch.object(task_impl, 'create_task_route_impl', new_callable=AsyncMock) as mock_impl:
        mock_impl.return_value = mock_task_response
        
        response = await gateway_client.post(
            f"{router_prefix}/public/projects/{mock_project.id}/tasks/new",
            params={
                "mode": PipelineExecutionMode.FULL,
                "force_exec": True,
                "target_nodes": "node-456",
            }
        )
        
        assert response.status_code == status.HTTP_200_OK
        assert mock_impl.call_args.kwargs["target_nodes"] == ["node-456"]
        # mock_impl.assert_called_once_with(
        #     session=db_session,
        #     user=mock_user,
        #     project=mock_project,
        #     target_nodes=["node-456"],
        #     mode=PipelineExecutionMode.FULL,
        #     force_exec=True,
        #     source=TaskSource.API,
        # )


@pytest.mark.asyncio
async def test_create_task_with_light_mode(
    gateway_client,
    router_prefix,
    set_current_user,
    set_current_project,
    mock_user,
    mock_project,
    db_session,
):
    """Тест создания задачи в легком режиме выполнения"""
    set_current_user(mock_user)
    set_current_project(mock_project)
    
    mock_task_response = TaskResponse(
        task_id="task-123",
        status=TaskExecutionStatus.PENDING,
        source=TaskSource.API,
        created_at="2024-01-01T00:00:00",
        success=True,
        message="Task created",
    )
    
    with patch.object(task_impl, 'create_task_route_impl', new_callable=AsyncMock) as mock_impl:
        mock_impl.return_value = mock_task_response
        
        response = await gateway_client.post(
            f"{router_prefix}/public/projects/{mock_project.id}/tasks/new",
            params={"mode": PipelineExecutionMode.METADATA_ONLY}
        )
        
        assert response.status_code == status.HTTP_200_OK
        assert mock_impl.call_args.kwargs["target_nodes"] is None
        # mock_impl.assert_called_once_with(
        #     session=db_session,
        #     user=mock_user,
        #     project=mock_project,
        #     target_nodes=None,
        #     mode=PipelineExecutionMode.METADATA_ONLY,
        #     force_exec=False,
        #     source=TaskSource.API,
        # )
