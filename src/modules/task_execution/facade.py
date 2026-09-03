"""Public composition API for task execution callers."""

from src.db import AsyncSessionLocal
from src.schemas.internal import TaskInternal

import config

from .domain.entities import EnqueueTaskResult
from .flow.use_cases import (
    ClaimTaskUseCase,
    CreatePendingExecutionUseCase,
    EnqueueTaskUseCase,
    FailPendingExecutionUseCase,
    FinalizeReconciledExecutionUseCase,
    FinalizeTaskUseCase,
    GetTaskExecutionUseCase,
    KillTaskUseCase,
    ListExecutionsForReconciliationUseCase,
    ListWorkerOwnedActiveExecutionsUseCase,
    MarkTaskRunningUseCase,
    PublishPendingDispatchesUseCase,
    ReleaseNestedWaitUseCase,
    RequestStopUseCase,
    ReserveNestedWaitUseCase,
    TerminateExecutionUseCase,
)
from .infra.gateways import (
    CeleryTaskTransport,
    RedisNestedWaitReservationGateway,
    ValkeyTaskCancellationGateway,
)
from .infra.repositories import SQLTaskExecutionRepository


class TaskExecutionFacade:
    def __init__(self, *, session_factory, celery_app) -> None:
        repository = SQLTaskExecutionRepository(session_factory)
        transport = CeleryTaskTransport(celery_app)
        cancellation = ValkeyTaskCancellationGateway(
            session_factory,
            redis_url=config.CELERY.CELERY_BROKER_URL,
            poll_interval_sec=config.TASK_WORKER.TASK_CANCELLATION_POLL_INTERVAL_SEC,
        )
        nested_wait_gateway = RedisNestedWaitReservationGateway(config.CELERY.CELERY_BROKER_URL)

        self.enqueue_task = EnqueueTaskUseCase(repository, transport)
        self.create_pending_execution = CreatePendingExecutionUseCase(repository)
        self.fail_pending_execution = FailPendingExecutionUseCase(repository)
        self.publish_pending_dispatches = PublishPendingDispatchesUseCase(repository, transport)
        self.claim_task = ClaimTaskUseCase(repository)
        self.mark_task_running = MarkTaskRunningUseCase(repository)
        self.finalize_task = FinalizeTaskUseCase(repository)
        self.finalize_reconciled = FinalizeReconciledExecutionUseCase(repository)
        self.get_task = GetTaskExecutionUseCase(repository)
        self.list_for_reconciliation = ListExecutionsForReconciliationUseCase(repository)
        self.request_stop = RequestStopUseCase(repository, cancellation, transport)
        self.kill_task = KillTaskUseCase(repository, cancellation, transport)
        self.list_worker_owned_active = ListWorkerOwnedActiveExecutionsUseCase(repository)
        self.terminate_execution = TerminateExecutionUseCase(transport)
        self.reserve_nested_wait = ReserveNestedWaitUseCase(nested_wait_gateway)
        self.release_nested_wait = ReleaseNestedWaitUseCase(nested_wait_gateway)
        self.transport = transport
        self.cancellation = cancellation
        self.nested_wait_gateway = nested_wait_gateway

    async def enqueue_task_internal(self, task: TaskInternal) -> EnqueueTaskResult:
        """Boundary adapter kept here so legacy callers do not import module infra."""
        from .infra.mappers import task_internal_to_execution

        return await self.enqueue_task.execute(
            execution=task_internal_to_execution(task),
            payload=task.model_dump(mode="json"),
        )


def build_task_execution_facade(*, celery_app, session_factory=AsyncSessionLocal) -> TaskExecutionFacade:
    return TaskExecutionFacade(session_factory=session_factory, celery_app=celery_app)


class TaskLifecycleCommands:
    """Composition root for lifecycle writes that do not require task transport."""

    def __init__(self, *, session_factory=AsyncSessionLocal) -> None:
        repository = SQLTaskExecutionRepository(session_factory)
        self.create_pending_execution = CreatePendingExecutionUseCase(repository)
        self.fail_pending_execution = FailPendingExecutionUseCase(repository)


def build_task_lifecycle_commands(*, session_factory=AsyncSessionLocal) -> TaskLifecycleCommands:
    return TaskLifecycleCommands(session_factory=session_factory)
