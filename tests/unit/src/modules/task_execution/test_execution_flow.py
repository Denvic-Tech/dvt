from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from src.modules.task_execution.domain.entities import DispatchOutboxItem, EnqueueTaskResult, TaskExecution
from src.modules.task_execution.domain.policies import (
    can_claim,
    can_supersede,
    decide_nested_wait_reservation,
)
from src.modules.task_execution.flow.use_cases import (
    ClaimTaskUseCase,
    EnqueueTaskUseCase,
    KillTaskUseCase,
    PublishPendingDispatchesUseCase,
    RequestStopUseCase,
    ReserveNestedWaitUseCase,
)


class _Repository:
    def __init__(self, dispatches=()):
        self.dispatches = list(dispatches)
        self.claim_result = True
        self.enqueued = []
        self.published = []
        self.failures = []
        self.stop_result = None
        self.stop_calls = []

    async def enqueue_with_dispatch(self, execution, payload):
        self.enqueued.append((execution, payload))
        return EnqueueTaskResult(execution=execution)

    async def claim(self, *, task_id, worker_id):
        return self.claim_result

    async def pending_dispatches(self, *, limit):
        return self.dispatches[:limit]

    async def mark_dispatch_published(self, *, dispatch_id):
        self.published.append(dispatch_id)

    async def record_dispatch_failure(self, *, dispatch_id, error):
        self.failures.append((dispatch_id, error))

    async def request_stop(self, *, task_id, reason, hard):
        self.stop_calls.append({"task_id": task_id, "reason": reason, "hard": hard})
        return self.stop_result


class _Transport:
    def __init__(self, failing_task_id=None):
        self.failing_task_id = failing_task_id
        self.calls = []
        self.revokes = []

    def publish(self, *, task_id, payload):
        if task_id == self.failing_task_id:
            raise RuntimeError("broker unavailable")
        self.calls.append((task_id, payload))

    def revoke(self, *, task_id, terminate=False):
        self.revokes.append({"task_id": task_id, "terminate": terminate})


def _execution() -> TaskExecution:
    return TaskExecution(
        task_id="new", user_id="user", organization_id="org", project_id="project",
        mode="full", source="API", status="PENDING",
    )


@pytest.mark.asyncio
async def test_enqueue_creates_durable_dispatch_through_repository_contract():
    repository = _Repository()
    execution = _execution()

    transport = _Transport()
    result = await EnqueueTaskUseCase(repository, transport).execute(
        execution=execution, payload={"task_id": "new"}
    )

    assert result.execution == execution
    assert repository.enqueued == [(execution, {"task_id": "new"})]


@pytest.mark.asyncio
async def test_enqueue_best_effort_revokes_already_published_superseded_task():
    repository = _Repository()
    current = _execution()
    stale = TaskExecution(
        task_id="old", user_id="user", organization_id="org", project_id="project",
        mode="full", source="API", status="CANCELLED",
        termination_reason="SUPERSEDED_BY_NEWER_EXECUTION",
    )
    repository.enqueue_with_dispatch = AsyncMock(
        return_value=EnqueueTaskResult(execution=current, superseded=(stale,))
    )
    transport = _Transport()

    await EnqueueTaskUseCase(repository, transport).execute(
        execution=current,
        payload={"task_id": "new"},
    )

    assert transport.revokes == [{"task_id": "old", "terminate": False}]


@pytest.mark.asyncio
async def test_duplicate_delivery_is_rejected_by_atomic_claim_gate():
    repository = _Repository()
    use_case = ClaimTaskUseCase(repository)

    assert await use_case.execute(task_id="task", worker_id="worker-a") is True
    repository.claim_result = False
    assert await use_case.execute(task_id="task", worker_id="worker-b") is False


@pytest.mark.asyncio
async def test_publisher_leaves_failed_outbox_record_for_retry():
    now = datetime.now(tz=UTC)
    repository = _Repository([
        DispatchOutboxItem("one", "first", {"task_id": "first"}, now),
        DispatchOutboxItem("two", "second", {"task_id": "second"}, now),
    ])
    transport = _Transport(failing_task_id="second")

    count = await PublishPendingDispatchesUseCase(repository, transport).execute()

    assert count == 1
    assert repository.published == ["one"]
    assert repository.failures == [("two", "broker unavailable")]


class _Cancellation:
    def __init__(self):
        self.notifications = []

    async def notify_stop(self, *, task_id):
        self.notifications.append(task_id)


@pytest.mark.asyncio
async def test_request_stop_notifies_active_execution_without_celery_control_task():
    repository = _Repository()
    repository.stop_result = TaskExecution(
        task_id="task", user_id="u", organization_id="o", project_id="p",
        mode="full", source="API", status="CANCEL_REQUESTED", termination_reason="USER_STOP",
    )
    transport = _Transport()
    cancellation = _Cancellation()

    result = await RequestStopUseCase(repository, cancellation, transport).execute(
        task_id="task", reason="USER_STOP"
    )

    assert result.status == "CANCEL_REQUESTED"
    assert cancellation.notifications == ["task"]
    assert transport.revokes == []
    assert repository.stop_calls == [{"task_id": "task", "reason": "USER_STOP", "hard": False}]


@pytest.mark.asyncio
async def test_kill_active_execution_terminates_child_immediately():
    repository = _Repository()
    repository.stop_result = TaskExecution(
        task_id="task", user_id="u", organization_id="o", project_id="p",
        mode="full", source="API", status="CANCEL_REQUESTED", termination_reason="USER_HARD_STOP",
    )
    transport = _Transport()
    cancellation = _Cancellation()

    result = await KillTaskUseCase(repository, cancellation, transport).execute(
        task_id="task", reason="USER_HARD_STOP"
    )

    assert result.status == "CANCEL_REQUESTED"
    assert cancellation.notifications == ["task"]
    assert transport.revokes == [{"task_id": "task", "terminate": True}]
    assert repository.stop_calls == [
        {"task_id": "task", "reason": "USER_HARD_STOP", "hard": True}
    ]


class _NestedWaitGateway:
    def __init__(self):
        self.reservations = {}

    async def list(self):
        return tuple(self.reservations.values())

    async def get(self, *, parent_task_id):
        return self.reservations.get(parent_task_id)

    async def reserve(self, reservation, *, max_waiters):
        if len(self.reservations) >= max_waiters:
            return False
        self.reservations[reservation.parent_task_id] = reservation
        return True


@pytest.mark.asyncio
async def test_nested_wait_reservation_prevents_all_workers_becoming_waiters():
    gateway = _NestedWaitGateway()
    use_case = ReserveNestedWaitUseCase(gateway)

    first = await use_case.execute(
        parent_task_id="parent-a",
        child_task_id="child-a",
        origin_worker_id="worker-a",
        alive_worker_ids=["worker-a", "worker-b"],
    )
    second = await use_case.execute(
        parent_task_id="parent-b",
        child_task_id="child-b",
        origin_worker_id="worker-b",
        alive_worker_ids=["worker-a", "worker-b"],
    )

    assert first.accepted is True
    assert second.accepted is False
    assert "deadlock" in second.error.lower()


def test_nested_wait_policy_rejects_single_worker_but_allows_busy_peer_to_exist():
    rejected = decide_nested_wait_reservation(
        origin_worker_id="worker-a",
        alive_worker_ids=["worker-a"],
        reserved_origin_worker_ids=[],
    )
    accepted = decide_nested_wait_reservation(
        origin_worker_id="worker-a",
        alive_worker_ids=["worker-a", "worker-b"],
        reserved_origin_worker_ids=[],
    )

    assert rejected.accepted is False
    assert accepted.accepted is True


def test_lifecycle_and_supersession_policy_preserve_node_child_tasks():
    assert can_claim("QUEUED")
    assert can_claim("ASSIGNED")
    assert not can_claim("STARTED")
    assert can_supersede(source="API", status="QUEUED")
    assert not can_supersede(source="NODE", status="QUEUED")
    assert not can_supersede(source="SCHEDULER", status="RUNNING")
