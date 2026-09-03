from __future__ import annotations

import asyncio
import socket
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel import Session
from usrak.core.security import hash_password

from services.orchestrator import task_finalizer
from services.orchestrator.execution_registry import TaskExecutionRegistry
from services.orchestrator.execution_supervisor import TaskExecutionSupervisor

from src import enums
from src.models.organization import OrganizationRecord
from src.modules.project.infra.db_models import ProjectRecord
from src.modules.task_execution.domain.entities import NestedWaitReservation, TaskExecution
from src.modules.task_execution.domain.types import (
    TaskExecutionStatus,
    TaskSource,
    TaskTerminationReason,
)
from src.modules.task_execution.flow.use_cases import (
    FailPendingExecutionUseCase,
    FinalizeReconciledExecutionUseCase,
    ListWorkerOwnedActiveExecutionsUseCase,
    PublishPendingDispatchesUseCase,
    RequestStopUseCase,
    ReserveNestedWaitUseCase,
)
from src.modules.task_execution.infra.db_models import TaskRecord
from src.modules.task_execution.infra.gateways.cancellation import ValkeyTaskCancellationGateway
from src.modules.task_execution.infra.gateways.nested_wait import RedisNestedWaitReservationGateway
from src.modules.task_execution.infra.repositories import SQLTaskExecutionRepository
from src.modules.user.infra.db_models import UserRecord
from src.pipeline.execution_mode import PipelineExecutionMode

import config

pytestmark = pytest.mark.docker_required


class _Transport:
    def __init__(self) -> None:
        self.published: list[str] = []

    def publish(self, *, task_id: str, payload) -> None:
        self.published.append(task_id)

    def revoke(self, *, task_id: str, terminate: bool = False) -> None:
        return None


@pytest.fixture()
def execution_identity(test_db_engine):
    suffix = uuid4().hex
    org = OrganizationRecord(id=f"org-{suffix}", name=f"Task execution org {suffix}")
    user = UserRecord(
        id=f"user-{suffix}",
        email=f"task-{suffix}@example.com",
        hashed_password=hash_password("TestPassword123"),
        auth_provider="email",
        is_verified=True,
        is_active=True,
        role=enums.DVTDefaultRoles.ADMIN,
        organization_id=org.id,
    )
    project = ProjectRecord(
        id=f"project-{suffix}",
        name="Task execution integration",
        user_id=user.id,
        organization_id=org.id,
    )
    org_id = str(org.id)
    user_id = str(user.id)
    project_id = str(project.id)
    with Session(test_db_engine) as session:
        session.add(org)
        session.flush()
        session.add(user)
        session.flush()
        session.add(project)
        session.commit()
    try:
        yield org_id, user_id, project_id
    finally:
        with Session(test_db_engine) as session:
            session.execute(sa.delete(TaskRecord).where(TaskRecord.project_id == project_id))
            session.execute(sa.delete(ProjectRecord).where(ProjectRecord.id == project_id))
            session.execute(sa.delete(UserRecord).where(UserRecord.id == user_id))
            session.execute(sa.delete(OrganizationRecord).where(OrganizationRecord.id == org_id))
            session.commit()


def _redis_url(redis_container) -> str:
    return (
        f"redis://{redis_container.get_container_host_ip()}:"
        f"{redis_container.get_exposed_port(6379)}/0"
    )


def _unavailable_redis_url() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    return f"redis://127.0.0.1:{port}/0"


def _execution(
    *,
    task_id: str,
    org_id: str,
    user_id: str,
    project_id: str,
) -> TaskExecution:
    return TaskExecution(
        task_id=task_id,
        user_id=user_id,
        organization_id=org_id,
        project_id=project_id,
        mode=PipelineExecutionMode.FULL,
        source=TaskSource.API,
        status=TaskExecutionStatus.PENDING,
    )


@pytest.fixture()
def repository(test_db_async_engine):
    factory = async_sessionmaker(test_db_async_engine, expire_on_commit=False)
    return SQLTaskExecutionRepository(factory), factory


@pytest.mark.asyncio(loop_scope="session")
async def test_nested_admission_rejection_atomically_fails_pending_execution(
    repository,
    execution_identity,
    test_db_engine,
):
    repo, _factory = repository
    org_id, user_id, project_id = execution_identity
    task_id = f"nested-rejected-{uuid4().hex}"
    with Session(test_db_engine) as session:
        session.add(
            TaskRecord(
                task_id=task_id,
                mode=PipelineExecutionMode.FULL,
                status=TaskExecutionStatus.PENDING,
                source=TaskSource.NODE,
                user_id=user_id,
                organization_id=org_id,
                project_id=project_id,
            )
        )
        session.commit()

    failed = await FailPendingExecutionUseCase(repo).execute(
        task_id=task_id,
        termination_reason=TaskTerminationReason.NESTED_WAIT_CAPACITY_LOST,
        message="nested wait capacity unavailable",
    )

    assert failed is not None
    assert failed.status == TaskExecutionStatus.ERROR
    assert failed.termination_reason == TaskTerminationReason.NESTED_WAIT_CAPACITY_LOST
    with Session(test_db_engine) as session:
        row = session.exec(sa.select(TaskRecord).where(TaskRecord.task_id == task_id)).scalar_one()
    assert row.status == TaskExecutionStatus.ERROR
    assert row.termination_reason == TaskTerminationReason.NESTED_WAIT_CAPACITY_LOST
    assert row.message == "nested wait capacity unavailable"
    assert await repo.pending_dispatches(limit=10) == []


@pytest.mark.asyncio(loop_scope="session")
async def test_durable_outbox_survives_publisher_recreation(repository, execution_identity):
    repo, factory = repository
    org_id, user_id, project_id = execution_identity
    task_id = f"task-{uuid4().hex}"
    await repo.enqueue_with_dispatch(
        _execution(task_id=task_id, org_id=org_id, user_id=user_id, project_id=project_id),
        {"task_id": task_id},
    )

    # Simulated Orchestrator restart: new repository/use-case objects, same DB.
    restarted_repo = SQLTaskExecutionRepository(factory)
    transport = _Transport()
    published = await PublishPendingDispatchesUseCase(restarted_repo, transport).execute()

    assert published == 1
    assert transport.published == [task_id]
    assert await restarted_repo.pending_dispatches(limit=10) == []


@pytest.mark.asyncio(loop_scope="session")
async def test_duplicate_delivery_has_single_atomic_claim(repository, execution_identity):
    repo, _factory = repository
    org_id, user_id, project_id = execution_identity
    task_id = f"task-{uuid4().hex}"
    await repo.enqueue_with_dispatch(
        _execution(task_id=task_id, org_id=org_id, user_id=user_id, project_id=project_id),
        {"task_id": task_id},
    )

    first, second = await asyncio.gather(
        repo.claim(task_id=task_id, worker_id="worker-a"),
        repo.claim(task_id=task_id, worker_id="worker-b"),
    )

    assert sorted([first, second]) == [False, True]


@pytest.mark.asyncio(loop_scope="session")
async def test_concurrent_enqueue_cannot_let_older_task_supersede_newer(
    repository,
    execution_identity,
    test_db_engine,
):
    repo, factory = repository
    org_id, user_id, project_id = execution_identity
    older_id = f"older-{uuid4().hex}"
    newer_id = f"newer-{uuid4().hex}"
    base = datetime.now(tz=UTC)

    with Session(test_db_engine) as session:
        session.add_all([
            TaskRecord(
                task_id=older_id,
                mode=PipelineExecutionMode.FULL,
                status=TaskExecutionStatus.PENDING,
                source=TaskSource.API,
                queued_at=base,
                user_id=user_id,
                organization_id=org_id,
                project_id=project_id,
            ),
            TaskRecord(
                task_id=newer_id,
                mode=PipelineExecutionMode.FULL,
                status=TaskExecutionStatus.PENDING,
                source=TaskSource.API,
                queued_at=base + timedelta(microseconds=1),
                user_id=user_id,
                organization_id=org_id,
                project_id=project_id,
            ),
        ])
        session.commit()

    older = _execution(task_id=older_id, org_id=org_id, user_id=user_id, project_id=project_id)
    newer = _execution(task_id=newer_id, org_id=org_id, user_id=user_id, project_id=project_id)
    await asyncio.gather(
        repo.enqueue_with_dispatch(newer, {"task_id": newer_id}),
        SQLTaskExecutionRepository(factory).enqueue_with_dispatch(older, {"task_id": older_id}),
    )

    async with factory() as session:
        rows = {
            row.task_id: row
            for row in (
                await session.scalars(
                    sa.select(TaskRecord).where(TaskRecord.task_id.in_((older_id, newer_id)))
                )
            ).all()
        }

    assert rows[older_id].status == TaskExecutionStatus.CANCELLED
    assert rows[older_id].termination_reason == TaskTerminationReason.SUPERSEDED_BY_NEWER_EXECUTION
    assert rows[newer_id].status == TaskExecutionStatus.QUEUED


@pytest.mark.asyncio(loop_scope="session")
async def test_reversed_enqueue_arrival_keeps_only_persisted_newest_root_runnable(
    repository,
    execution_identity,
    test_db_engine,
):
    repo, _factory = repository
    org_id, user_id, project_id = execution_identity
    older_id = f"older-reversed-{uuid4().hex}"
    newer_id = f"newer-reversed-{uuid4().hex}"
    base = datetime.now(tz=UTC)

    with Session(test_db_engine) as session:
        session.add_all([
            TaskRecord(
                task_id=older_id,
                mode=PipelineExecutionMode.FULL,
                status=TaskExecutionStatus.PENDING,
                source=TaskSource.API,
                queued_at=base,
                user_id=user_id,
                organization_id=org_id,
                project_id=project_id,
            ),
            TaskRecord(
                task_id=newer_id,
                mode=PipelineExecutionMode.FULL,
                status=TaskExecutionStatus.PENDING,
                source=TaskSource.API,
                queued_at=base + timedelta(seconds=1),
                user_id=user_id,
                organization_id=org_id,
                project_id=project_id,
            ),
        ])
        session.commit()

    newer_result = await repo.enqueue_with_dispatch(
        _execution(task_id=newer_id, org_id=org_id, user_id=user_id, project_id=project_id),
        {"task_id": newer_id},
    )
    older_result = await repo.enqueue_with_dispatch(
        _execution(task_id=older_id, org_id=org_id, user_id=user_id, project_id=project_id),
        {"task_id": older_id},
    )

    assert newer_result.execution.status == TaskExecutionStatus.QUEUED
    assert older_result.execution.status == TaskExecutionStatus.CANCELLED
    assert older_result.execution.termination_reason == (
        TaskTerminationReason.SUPERSEDED_BY_NEWER_EXECUTION
    )
    pending = await repo.pending_dispatches(limit=10)
    assert [item.task_id for item in pending] == [newer_id]


@pytest.mark.asyncio(loop_scope="session")
async def test_cancel_requested_cannot_race_into_success(repository, execution_identity):
    repo, _factory = repository
    org_id, user_id, project_id = execution_identity
    task_id = f"task-{uuid4().hex}"
    await repo.enqueue_with_dispatch(
        _execution(task_id=task_id, org_id=org_id, user_id=user_id, project_id=project_id),
        {"task_id": task_id},
    )
    assert await repo.claim(task_id=task_id, worker_id="worker-a")
    assert await repo.mark_running(task_id=task_id, worker_id="worker-a")
    task = await repo.request_stop(
        task_id=task_id,
        reason=TaskTerminationReason.USER_STOP,
        hard=False,
    )
    assert task is not None and task.status == TaskExecutionStatus.CANCEL_REQUESTED

    assert not await repo.finalize(task_id=task_id, worker_id="worker-a", status="SUCCESS")
    assert await repo.finalize(
        task_id=task_id,
        worker_id="worker-a",
        status="CANCELLED",
        termination_reason=TaskTerminationReason.USER_STOP,
    )


@pytest.mark.asyncio(loop_scope="session")
async def test_postgres_termination_precedence_upgrades_stop_to_oom_error(
    repository,
    execution_identity,
    test_db_engine,
):
    repo, _factory = repository
    org_id, user_id, project_id = execution_identity
    task_id = f"precedence-{uuid4().hex}"
    await repo.enqueue_with_dispatch(
        _execution(task_id=task_id, org_id=org_id, user_id=user_id, project_id=project_id),
        {"task_id": task_id},
    )
    assert await repo.claim(task_id=task_id, worker_id="worker-a")
    assert await repo.mark_running(task_id=task_id, worker_id="worker-a")

    first = await repo.request_stop(
        task_id=task_id,
        reason=TaskTerminationReason.USER_STOP,
        hard=False,
    )
    second = await repo.request_stop(
        task_id=task_id,
        reason=TaskTerminationReason.OOM_GUARD,
        hard=True,
    )

    assert first is not None and first.termination_reason == TaskTerminationReason.USER_STOP
    assert second is not None and second.termination_reason == TaskTerminationReason.OOM_GUARD
    assert not await repo.finalize(
        task_id=task_id,
        worker_id="worker-a",
        status="CANCELLED",
        termination_reason=TaskTerminationReason.USER_STOP,
    )
    assert await repo.finalize(task_id=task_id, worker_id="worker-a", status="ERROR")

    with Session(test_db_engine) as session:
        row = session.exec(sa.select(TaskRecord).where(TaskRecord.task_id == task_id)).scalar_one()
    assert row.status == TaskExecutionStatus.ERROR
    assert row.termination_reason == TaskTerminationReason.OOM_GUARD


class _SupervisorWorker:
    def __init__(self, *, alive: bool) -> None:
        self.alive = alive

    def is_alive(self, *_args) -> bool:
        return self.alive


class _SupervisorWorkerRegistry:
    def __init__(self, worker=None) -> None:
        self.worker = worker

    def reap_dead_workers(self, _now):
        return []

    def get(self, _worker_id):
        return self.worker

    def mark_busy(self, **_kwargs):
        return None

    def mark_idle(self, **_kwargs):
        return None


class _SupervisorScheduler:
    def __init__(self, worker=None) -> None:
        self.registry = _SupervisorWorkerRegistry(worker)


@pytest.mark.asyncio(loop_scope="session")
async def test_postgres_active_claim_without_telemetry_reconciles_worker_lost(
    repository,
    execution_identity,
    monkeypatch,
    test_db_engine,
):
    repo, _factory = repository
    org_id, user_id, project_id = execution_identity
    task_id = f"claim-lost-{uuid4().hex}"
    await repo.enqueue_with_dispatch(
        _execution(task_id=task_id, org_id=org_id, user_id=user_id, project_id=project_id),
        {"task_id": task_id},
    )
    assert await repo.claim(task_id=task_id, worker_id="worker-dead")

    facade = SimpleNamespace(
        list_worker_owned_active=ListWorkerOwnedActiveExecutionsUseCase(repo),
        finalize_reconciled=FinalizeReconciledExecutionUseCase(repo),
        release_nested_wait=SimpleNamespace(execute=AsyncMock()),
    )
    monkeypatch.setattr(
        "services.orchestrator.execution_supervisor.build_task_execution_facade",
        lambda **_kwargs: facade,
    )
    monkeypatch.setattr(
        "services.orchestrator.execution_supervisor.publish_task_terminal_event",
        AsyncMock(),
    )
    supervisor = TaskExecutionSupervisor(
        registry=TaskExecutionRegistry(),
        scheduler=_SupervisorScheduler(_SupervisorWorker(alive=False)),
    )

    await supervisor._reconcile_stale_executions()

    with Session(test_db_engine) as session:
        row = session.exec(sa.select(TaskRecord).where(TaskRecord.task_id == task_id)).scalar_one()
    assert row.status == TaskExecutionStatus.ERROR
    assert row.termination_reason == TaskTerminationReason.WORKER_LOST


@pytest.mark.asyncio(loop_scope="session")
async def test_postgres_running_recovers_after_orchestrator_restart_with_empty_registry(
    repository,
    execution_identity,
    monkeypatch,
    test_db_engine,
):
    repo, _factory = repository
    org_id, user_id, project_id = execution_identity
    task_id = f"restart-lost-{uuid4().hex}"
    await repo.enqueue_with_dispatch(
        _execution(task_id=task_id, org_id=org_id, user_id=user_id, project_id=project_id),
        {"task_id": task_id},
    )
    assert await repo.claim(task_id=task_id, worker_id="worker-gone")
    assert await repo.mark_running(task_id=task_id, worker_id="worker-gone")

    facade = SimpleNamespace(
        list_worker_owned_active=ListWorkerOwnedActiveExecutionsUseCase(repo),
        finalize_reconciled=FinalizeReconciledExecutionUseCase(repo),
        release_nested_wait=SimpleNamespace(execute=AsyncMock()),
    )
    monkeypatch.setattr(
        "services.orchestrator.execution_supervisor.build_task_execution_facade",
        lambda **_kwargs: facade,
    )
    monkeypatch.setattr(
        "services.orchestrator.execution_supervisor.publish_task_terminal_event",
        AsyncMock(),
    )
    supervisor = TaskExecutionSupervisor(
        registry=TaskExecutionRegistry(),
        scheduler=_SupervisorScheduler(None),
    )
    supervisor._started_at -= config.ORCHESTRATOR.ORCHESTRATOR_HEARTBEAT_TIMEOUT_SEC + 1

    await supervisor._reconcile_stale_executions()

    with Session(test_db_engine) as session:
        row = session.exec(sa.select(TaskRecord).where(TaskRecord.task_id == task_id)).scalar_one()
    assert row.status == TaskExecutionStatus.ERROR
    assert row.termination_reason == TaskTerminationReason.WORKER_LOST


@pytest.mark.asyncio(loop_scope="session")
async def test_post_commit_nested_wait_cleanup_failure_preserves_terminal_db_and_ws(
    repository,
    execution_identity,
    monkeypatch,
    test_db_engine,
):
    repo, factory = repository
    org_id, user_id, project_id = execution_identity
    task_id = f"redis-cleanup-failure-{uuid4().hex}"
    await repo.enqueue_with_dispatch(
        _execution(task_id=task_id, org_id=org_id, user_id=user_id, project_id=project_id),
        {"task_id": task_id},
    )
    assert await repo.claim(task_id=task_id, worker_id="worker-a")
    assert await repo.mark_running(task_id=task_id, worker_id="worker-a")

    release = AsyncMock(side_effect=RuntimeError("valkey unavailable"))
    finalize_reconciled = FinalizeReconciledExecutionUseCase(repo)
    facade = SimpleNamespace(
        finalize_reconciled=finalize_reconciled,
        release_nested_wait=SimpleNamespace(execute=release),
    )
    fake_ws = AsyncMock()
    fake_worker_registry = SimpleNamespace(mark_idle=lambda **_kwargs: None)
    monkeypatch.setattr(
        task_finalizer,
        "build_task_execution_facade",
        lambda **_kwargs: facade,
    )
    monkeypatch.setattr(
        task_finalizer,
        "get_task_execution_registry",
        lambda: TaskExecutionRegistry(),
    )
    monkeypatch.setattr(task_finalizer, "get_worker_registry", lambda: fake_worker_registry)
    monkeypatch.setattr(task_finalizer.shared_ws_forward, "get", AsyncMock(return_value=fake_ws))

    finalized = await task_finalizer.finalize_task_terminal_status(
        task_id=task_id,
        user_id=user_id,
        project_id=project_id,
        worker_id="worker-a",
        mode=PipelineExecutionMode.FULL,
        status=TaskExecutionStatus.ERROR,
        termination_reason=TaskTerminationReason.WORKER_LOST,
        error_message="worker lost",
    )

    assert finalized is True
    release.assert_awaited_once()
    fake_ws.send_message.assert_awaited_once()
    with Session(test_db_engine) as session:
        row = session.exec(sa.select(TaskRecord).where(TaskRecord.task_id == task_id)).scalar_one()
    assert row.status == TaskExecutionStatus.ERROR
    assert row.termination_reason == TaskTerminationReason.WORKER_LOST


@pytest.mark.asyncio(loop_scope="session")
async def test_valkey_stop_notification_has_postgres_fallback(
    repository,
    execution_identity,
    redis_container,
):
    repo, factory = repository
    org_id, user_id, project_id = execution_identity
    task_id = f"task-{uuid4().hex}"
    await repo.enqueue_with_dispatch(
        _execution(task_id=task_id, org_id=org_id, user_id=user_id, project_id=project_id),
        {"task_id": task_id},
    )
    assert await repo.claim(task_id=task_id, worker_id="worker-a")
    assert await repo.mark_running(task_id=task_id, worker_id="worker-a")

    gateway = ValkeyTaskCancellationGateway(
        factory,
        redis_url=_redis_url(redis_container),
        poll_interval_sec=0.05,
    )
    waiter = asyncio.create_task(gateway.wait_for_stop(task_id=task_id))
    await asyncio.sleep(0.05)
    await repo.request_stop(
        task_id=task_id,
        reason=TaskTerminationReason.USER_STOP,
        hard=False,
    )
    # Deliberately do not publish the Valkey wakeup: DB polling is the recovery path.
    assert await asyncio.wait_for(waiter, timeout=2) == TaskTerminationReason.USER_STOP


@pytest.mark.asyncio(loop_scope="session")
async def test_stop_watcher_polls_postgres_when_valkey_is_unavailable_before_subscribe(
    repository,
    execution_identity,
):
    repo, factory = repository
    org_id, user_id, project_id = execution_identity
    task_id = f"stop-no-valkey-{uuid4().hex}"
    await repo.enqueue_with_dispatch(
        _execution(task_id=task_id, org_id=org_id, user_id=user_id, project_id=project_id),
        {"task_id": task_id},
    )
    assert await repo.claim(task_id=task_id, worker_id="worker-a")
    assert await repo.mark_running(task_id=task_id, worker_id="worker-a")

    gateway = ValkeyTaskCancellationGateway(
        factory,
        redis_url=_unavailable_redis_url(),
        poll_interval_sec=0.05,
    )
    waiter = asyncio.create_task(gateway.wait_for_stop(task_id=task_id))
    await asyncio.sleep(0.15)
    stopped = await repo.request_stop(
        task_id=task_id,
        reason=TaskTerminationReason.USER_STOP,
        hard=False,
    )

    assert stopped is not None and stopped.status == TaskExecutionStatus.CANCEL_REQUESTED
    assert await asyncio.wait_for(waiter, timeout=2) == TaskTerminationReason.USER_STOP


@pytest.mark.asyncio(loop_scope="session")
async def test_redis_publish_failure_after_db_stop_does_not_reject_request(
    repository,
    execution_identity,
):
    repo, factory = repository
    org_id, user_id, project_id = execution_identity
    task_id = f"stop-publish-failure-{uuid4().hex}"
    await repo.enqueue_with_dispatch(
        _execution(task_id=task_id, org_id=org_id, user_id=user_id, project_id=project_id),
        {"task_id": task_id},
    )
    assert await repo.claim(task_id=task_id, worker_id="worker-a")
    assert await repo.mark_running(task_id=task_id, worker_id="worker-a")

    gateway = ValkeyTaskCancellationGateway(
        factory,
        redis_url=_unavailable_redis_url(),
        poll_interval_sec=0.05,
    )
    result = await RequestStopUseCase(repo, gateway, _Transport()).execute(
        task_id=task_id,
        reason=TaskTerminationReason.USER_STOP,
    )

    assert result is not None
    assert result.status == TaskExecutionStatus.CANCEL_REQUESTED
    async with factory() as session:
        row = await session.scalar(sa.select(TaskRecord).where(TaskRecord.task_id == task_id))
    assert row is not None
    assert row.status == TaskExecutionStatus.CANCEL_REQUESTED
    assert row.termination_reason == TaskTerminationReason.USER_STOP


@pytest.mark.asyncio(loop_scope="session")
async def test_stop_watcher_reconnects_to_valkey_without_mutating_lifecycle(
    repository,
    execution_identity,
    redis_container,
):
    repo, factory = repository
    org_id, user_id, project_id = execution_identity
    task_id = f"stop-reconnect-{uuid4().hex}"
    await repo.enqueue_with_dispatch(
        _execution(task_id=task_id, org_id=org_id, user_id=user_id, project_id=project_id),
        {"task_id": task_id},
    )
    assert await repo.claim(task_id=task_id, worker_id="worker-a")
    assert await repo.mark_running(task_id=task_id, worker_id="worker-a")

    gateway = ValkeyTaskCancellationGateway(
        factory,
        redis_url=_unavailable_redis_url(),
        poll_interval_sec=0.05,
    )
    waiter = asyncio.create_task(gateway.wait_for_stop(task_id=task_id))
    await asyncio.sleep(0.15)

    # Simulate Valkey becoming reachable again. The gateway must reconnect on its
    # own while PostgreSQL remains the only lifecycle writer.
    gateway._redis_url = _redis_url(redis_container)
    await asyncio.sleep(0.15)
    stopped = await repo.request_stop(
        task_id=task_id,
        reason=TaskTerminationReason.USER_STOP,
        hard=False,
    )
    assert stopped is not None and stopped.status == TaskExecutionStatus.CANCEL_REQUESTED
    await gateway.notify_stop(task_id=task_id)

    assert await asyncio.wait_for(waiter, timeout=2) == TaskTerminationReason.USER_STOP
    async with factory() as session:
        row = await session.scalar(sa.select(TaskRecord).where(TaskRecord.task_id == task_id))
    assert row is not None
    assert row.status == TaskExecutionStatus.CANCEL_REQUESTED
    assert row.termination_reason == TaskTerminationReason.USER_STOP


@pytest.mark.asyncio(loop_scope="session")
async def test_real_valkey_nested_wait_reservation_prevents_mutual_deadlock(redis_container):
    gateway = RedisNestedWaitReservationGateway(
        _redis_url(redis_container),
        key=f"task_execution:test:nested:{uuid4().hex}",
    )
    use_case = ReserveNestedWaitUseCase(gateway)

    first, second = await asyncio.gather(
        use_case.execute(
            parent_task_id="parent-a",
            child_task_id="child-a",
            origin_worker_id="worker-a",
            alive_worker_ids=["worker-a", "worker-b"],
        ),
        use_case.execute(
            parent_task_id="parent-b",
            child_task_id="child-b",
            origin_worker_id="worker-b",
            alive_worker_ids=["worker-a", "worker-b"],
        ),
    )

    assert sum(decision.accepted for decision in (first, second)) == 1
    assert len(await gateway.list()) == 1


@pytest.mark.asyncio(loop_scope="session")
async def test_real_valkey_nested_wait_rebalance_evicts_newest_when_capacity_shrinks(redis_container):
    gateway = RedisNestedWaitReservationGateway(
        _redis_url(redis_container),
        key=f"task_execution:test:nested-rebalance:{uuid4().hex}",
    )
    base = datetime.now(tz=UTC)
    older = NestedWaitReservation(
        parent_task_id="parent-old",
        child_task_id="child-old",
        origin_worker_id="worker-a",
        created_at=base,
    )
    newer = NestedWaitReservation(
        parent_task_id="parent-new",
        child_task_id="child-new",
        origin_worker_id="worker-b",
        created_at=base + timedelta(seconds=1),
    )

    assert await gateway.reserve(older, max_waiters=2)
    assert await gateway.reserve(newer, max_waiters=2)
    evicted = await gateway.rebalance(max_waiters=1)

    assert [item.parent_task_id for item in evicted] == ["parent-new"]
    assert [item.parent_task_id for item in await gateway.list()] == ["parent-old"]
