import asyncio
import socket
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa
import uvicorn
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker

from services.gateway.routes.internal.ai_mcp import schedules
from services.gateway.routes.internal.ai_mcp.access import get_accessible_project
from services.gateway.routes.internal.ai_mcp.auth import MCPPrincipal
from services.gateway.routes.internal.ai_mcp.errors import AIMCPHTTPError
from services.gateway.routes.internal.ai_mcp.projects import create_project
from services.project_scheduler.deps import get_project_scheduler_manager
from services.project_scheduler.routes.projects import router as scheduler_router

from src.clients.scheduler_client import SchedulerClient
from src.managers import project_scheduler as scheduler_module
from src.managers.project_scheduler import ProjectSchedulerManager
from src.models import OrganizationRecord
from src.modules.ai_mcp_access.domain.entities import MCPToken
from src.modules.ai_mcp_access.domain.types import ResourceScopeMode
from src.modules.ai_mcp_access.domain.value_objects import MCPAccessScope, ResourceScope
from src.modules.pipeline_graph.infra.db_models import GraphNodeRecord
from src.modules.project.domain import ProjectScheduleRunStatus
from src.modules.project.infra.db_models import (
    ProjectFolderRecord,
    ProjectRecord,
    ProjectScheduleRecord,
    ProjectScheduleRunRecord,
)
from src.modules.task_execution.domain.types import TaskExecutionStatus, TaskSource
from src.modules.task_execution.infra.db_models import TaskRecord
from src.modules.user.infra.db_models import UserRecord
from src.pipeline.execution_mode import PipelineExecutionMode

pytestmark = [pytest.mark.docker_required, pytest.mark.asyncio(loop_scope="session")]


def restrict(principal, project_id):
    scope = replace(principal.token.access_scope, projects=ResourceScope(
        ResourceScopeMode.SELECTED, frozenset({project_id}),
    ))
    return MCPPrincipal(user=principal.user, token=replace(principal.token, access_scope=scope))


@pytest_asyncio.fixture(loop_scope="session")
async def project_context(test_db_async_engine):
    factory = async_sessionmaker(test_db_async_engine, expire_on_commit=False)
    async with factory() as session:
        org = OrganizationRecord(name=f"MCP test {uuid4()}")
        other_org = OrganizationRecord(name=f"Other MCP test {uuid4()}")
        session.add_all([org, other_org])
        await session.flush()
        user = UserRecord(
            email=f"mcp-{uuid4()}@example.com", hashed_password="unused", auth_provider="email",
            is_verified=True, is_active=True, role="admin", organization_id=org.id,
        )
        session.add(user)
        await session.flush()
        folder = ProjectFolderRecord(name="Allowed", user_id=user.id, organization_id=org.id)
        hidden_folder = ProjectFolderRecord(
            name="Hidden", user_id=user.id, organization_id=other_org.id,
        )
        session.add_all([folder, hidden_folder])
        await session.commit()
        scope = MCPAccessScope(
            projects=ResourceScope(ResourceScopeMode.ALL),
            db_connections=ResourceScope(ResourceScopeMode.ALL),
        )
        token = MCPToken(
            id=str(uuid4()), user_id=user.id, token_digest="unused", name="test",
            access_scope=scope, created_at=datetime.now(UTC),
        )
        yield session, MCPPrincipal(user=user, token=token), folder, hidden_folder


async def test_create_empty_project_and_enforce_scope(project_context):
    session, principal, folder, hidden_folder = project_context
    result = await create_project(
        session=session, principal=principal, name="  New ETL  ", folder_id=folder.id,
    )
    project = await session.get(ProjectRecord, result["id"])
    assert project.name == "New ETL"
    assert project.user_id == principal.user.id
    assert project.organization_id == principal.user.organization_id
    assert project.folder_id == folder.id
    assert result["graph_revision"] == 0
    assert result["store_enabled"] is False
    assert not (await session.execute(
        sa.select(GraphNodeRecord).where(GraphNodeRecord.project_id == project.id)
    )).scalars().all()

    before = await session.scalar(sa.select(sa.func.count()).select_from(ProjectRecord))
    restricted = restrict(principal, project.id)
    for actor, name, target_folder, code in [
        (restricted, "Not created", None, "SCOPE_DENIED"),
        (principal, "Not created", hidden_folder.id, "FOLDER_NOT_FOUND_OR_DENIED"),
        (principal, "Not created", "missing-folder", "FOLDER_NOT_FOUND_OR_DENIED"),
        (principal, "   ", None, "INVALID_ARGUMENTS"),
    ]:
        with pytest.raises(AIMCPHTTPError) as error:
            await create_project(
                session=session, principal=actor, name=name, folder_id=target_folder,
            )
        assert error.value.detail["code"] == code
    assert await session.scalar(sa.select(sa.func.count()).select_from(ProjectRecord)) == before

    hidden_project = ProjectRecord(
        name="Hidden", user_id=principal.user.id, organization_id=hidden_folder.organization_id,
    )
    session.add(hidden_project)
    await session.commit()
    with pytest.raises(AIMCPHTTPError):
        await get_accessible_project(session, principal, hidden_project.id)
    with pytest.raises(AIMCPHTTPError):
        await get_accessible_project(session, restricted, hidden_project.id)
    assert (await get_accessible_project(session, restricted, project.id)).id == project.id


@pytest_asyncio.fixture(loop_scope="session")
async def scheduler_service(test_db_async_engine, monkeypatch):
    # Real HTTP routes and client with isolated testcontainers PostgreSQL.
    monkeypatch.setattr(scheduler_module, "engine", test_db_async_engine)
    manager = ProjectSchedulerManager()
    manager.scheduler.start(paused=True)  # Do not execute pipelines in this contract test.
    app = FastAPI()
    app.include_router(scheduler_router)
    app.dependency_overrides[get_project_scheduler_manager] = lambda: manager
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="off"))
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        async with asyncio.timeout(10):
            while not server.started:
                if task.done():
                    await task
                await asyncio.sleep(0.01)
        monkeypatch.setattr(
            schedules, "SchedulerClient",
            lambda: SchedulerClient(scheduler_url=f"http://127.0.0.1:{port}"),
        )
        yield manager
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, 10)
        await manager.shutdown()
        sock.close()


@pytest.mark.parametrize("operation", ["set", "update", "enable", "disable"])
async def test_legacy_schedule_mode_persisted_over_http(
    project_context, scheduler_service, operation,
):
    session, principal, _, _ = project_context
    project = await create_project(session=session, principal=principal, name="Legacy schedule")
    project_id = project["id"]
    args = {"session": session, "principal": principal, "project_id": project_id}
    await scheduler_service.schedule_project(
        project_id=project_id, cron="15 2 * * *", mode=PipelineExecutionMode.METADATA_ONLY,
        force_exec=True, max_retries=3, scheduled_by_user_id=principal.user.id,
    )
    await schedules.set_project_schedule_enabled(**args, enabled=False)
    if operation == "set":
        await schedules.set_project_schedule(
            **args, cron="15 2 * * *", force_exec=True, max_retries=3,
        )
    elif operation == "update":
        await schedules.update_project_schedule(**args, patch={"max_retries": 3})
    else:
        await schedules.set_project_schedule_enabled(**args, enabled=operation == "enable")

    record = await session.scalar(
        sa.select(ProjectScheduleRecord).where(ProjectScheduleRecord.project_id == project_id)
    )
    expected_mode = (
        PipelineExecutionMode.METADATA_ONLY if operation == "disable" else PipelineExecutionMode.FULL
    )
    assert record.mode == expected_mode
    assert record.disabled == (operation in {"update", "disable"})
    assert record.cron == "15 2 * * *"
    assert record.force_exec is True
    assert record.max_retries == 3
    current = (await schedules.get_project_schedule(**args))["schedule"]
    assert "mode" not in current
    assert current["recent_runs"] == []


async def test_schedule_lifecycle_over_http(project_context, scheduler_service):
    session, principal, _, hidden_folder = project_context
    project = await create_project(session=session, principal=principal, name="Scheduled ETL")
    project_id = project["id"]
    args = {"session": session, "principal": principal, "project_id": project_id}
    assert await schedules.get_project_schedule(**args) == {"schedule": None}
    await schedules.set_project_schedule(**args, cron="15 2 * * *", force_exec=True, max_retries=3)
    current = (await schedules.get_project_schedule(**args))["schedule"]
    assert current["cron"] == "15 2 * * *"
    assert current["disabled"] is False
    assert current["next_run_time"] is not None
    assert current["scheduled_by_user_id"] == principal.user.id

    await schedules.update_project_schedule(
        **args, patch={"force_exec": False, "max_retries": 0},
    )
    current = (await schedules.get_project_schedule(**args))["schedule"]
    assert current["cron"] == "15 2 * * *"
    assert current["force_exec"] is False
    assert current["max_retries"] == 0

    # Persist a failed scheduled attempt and a waiting retry to check history and cancellation.
    now = datetime.now(UTC)
    record = await session.scalar(
        sa.select(ProjectScheduleRecord).where(ProjectScheduleRecord.project_id == project_id)
    )
    assert record.mode == PipelineExecutionMode.FULL
    chain = ProjectScheduleRunRecord(
        schedule_id=record.id, scheduled_at=now, status=ProjectScheduleRunStatus.WAITING_RETRY,
        attempt_number=1, max_retries=3, next_retry_at=now + timedelta(hours=1),
        last_error="password=hidden-value",
    )
    session.add(chain)
    await session.flush()
    task = TaskRecord(
        task_id=str(uuid4()), project_id=project_id, user_id=principal.user.id,
        organization_id=principal.user.organization_id, mode="full",
        status=TaskExecutionStatus.ERROR, source=TaskSource.SCHEDULER.value,
        queued_at=now, finished_at=now, message="password=hidden-value",
        schedule_run_id=chain.id, schedule_attempt=1,
    )
    session.add(task)
    await session.commit()
    current = (await schedules.get_project_schedule(**args))["schedule"]
    assert current["last_run_task_id"] == task.task_id
    assert current["last_run_status"] == "ERROR"
    assert current["recent_runs"][0]["task_id"] == task.task_id
    assert current["latest_run_chain"]["state"] == "WAITING_RETRY"
    assert "hidden-value" not in str(current)
    assert "[REDACTED]" in current["last_run_message"]

    await schedules.set_project_schedule_enabled(**args, enabled=False)
    await session.refresh(chain)
    assert chain.status == ProjectScheduleRunStatus.CANCELLED
    assert chain.finished_at is not None
    assert chain.next_retry_at is None
    await schedules.update_project_schedule(**args, patch={"cron": "0 3 * * *"})
    current = (await schedules.get_project_schedule(**args))["schedule"]
    assert current["disabled"] is True
    assert current["next_run_time"] is None
    assert current["cron"] == "0 3 * * *"
    await schedules.set_project_schedule_enabled(**args, enabled=True)
    current = (await schedules.get_project_schedule(**args))["schedule"]
    assert current["disabled"] is False
    assert current["cron"] == "0 3 * * *"

    await schedules.set_project_schedule_enabled(**args, enabled=False)
    await schedules.set_project_schedule(**args, cron="0 4 * * *")
    current = (await schedules.get_project_schedule(**args))["schedule"]
    assert current["disabled"] is False
    assert current["cron"] == "0 4 * * *"
    assert current["max_retries"] == 0

    sibling = await create_project(session=session, principal=principal, name="Sibling")
    await schedules.set_project_schedule(
        session=session, principal=principal, project_id=sibling["id"], cron="0 5 * * *",
    )
    hidden = ProjectRecord(
        name="Other org", user_id=principal.user.id, organization_id=hidden_folder.organization_id,
    )
    session.add(hidden)
    await session.commit()
    await scheduler_service.schedule_project(
        project_id=hidden.id, cron="0 6 * * *", scheduled_by_user_id=principal.user.id,
    )
    page = await schedules.list_project_schedules(session=session, principal=principal)
    ids = {item["project_id"] for item in page["items"]}
    assert {project_id, sibling["id"]} <= ids
    assert hidden.id not in ids
    restricted = restrict(principal, project_id)
    page = await schedules.list_project_schedules(
        session=session, principal=restricted, limit=1,
    )
    assert [item["project_id"] for item in page["items"]] == [project_id]
    assert page["next_cursor"] is None
    with pytest.raises(AIMCPHTTPError):
        await schedules.get_project_schedule(
            session=session, principal=restricted, project_id=sibling["id"],
        )
