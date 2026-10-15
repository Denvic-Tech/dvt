import asyncio
import time
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from usrak.core.dependencies.user import build_user_dependency
from usrak.core.enums import AuthMode

from services.gateway.deps.clients import get_orchestrator_client
from services.gateway.deps.system_info_manager import get_sys_info
from services.gateway.update_runtime import get_system_state_monitor

from src.clients.orchestrator_client import GrpcOrchestratorClient
from src.clients.scheduler_client import SchedulerClient, get_schedule_client
from src.crud import project as project_crud
from src.db.fastapi.dependencies import AsyncSessionDepends
from src.enums import DVTDefaultRoles, WorkerStatus
from src.logger import logger
from src.modules.project.infra.db_models import ProjectRecord
from src.modules.project.infra.queries import get_recent_scheduler_runs_by_project_ids
from src.modules.task_execution.domain.types import TERMINAL_STATUSES, TaskExecutionStatus
from src.modules.task_execution.infra.queries import (
    ProjectErrorStats,
    RunsWindowStats,
    TaskReadModel,
    compute_hourly_window,
    get_project_error_stats,
    get_recent_project_runs_by_project_ids,
    get_runs_window_stats,
)
from src.modules.user.infra.db_models import UserRecord
from src.modules.user.infra.fastapi.dependencies import UserAccessOnly
from src.schemas.http.system import SystemInfo, WorkerSystemInfo
from src.schemas.internal import ProjectScheduleResponse
from src.utils.access_control import AccessScope, get_access_scope
from src.utils.user_roles import user_has_global_access

from .schemas import (
    FailingProjectItemSchema,
    FailingProjectsWidgetSchema,
    RunsBucketSchema,
    RunsLast24hWidgetSchema,
    ScheduledRunItemSchema,
    ScheduledRunsWidgetSchema,
    ServiceStatusItemSchema,
    ServicesWidgetSchema,
    WorkersSummarySchema,
)

router = APIRouter(prefix="/widgets", tags=["Widgets"])

get_widgets_admin_user = build_user_dependency(
    auth_mode=AuthMode.ACCESS_ONLY,
    require_active=True,
    require_verified=True,
    require_roles=[DVTDefaultRoles.SUPERADMIN, DVTDefaultRoles.ADMIN],
)
UserAdminAccess = Annotated[UserRecord, Depends(get_widgets_admin_user)]
SchedulerClientDepends = Annotated[SchedulerClient, Depends(get_schedule_client)]
OrchestratorClientDepends = Annotated[GrpcOrchestratorClient, Depends(get_orchestrator_client)]
LimitQuery = Annotated[int, Query(ge=1, le=20, description="Максимум элементов")]

RUNS_WINDOW_HOURS = 24
FAILING_PROJECTS_WINDOW_DAYS = 7
FAILING_PROJECTS_STREAK_DEPTH = 10
SERVICE_CALL_TIMEOUT_SEC = 3.0


def _ensure_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


async def _get_visible_projects(
        session,
        *,
        project_ids: Sequence[str],
        access_scope: AccessScope,
) -> dict[str, ProjectRecord]:
    projects = await project_crud.get_projects_by_ids(
        session,
        project_ids=project_ids,
        organization_id=access_scope.organization_id,
        owner_user_id=access_scope.owner_user_id,
    )
    return {project.id: project for project in projects if not project.is_deleted}


# --- Запуски за 24 ч ---


def _to_runs_schema(stats: RunsWindowStats, *, generated_at: datetime) -> RunsLast24hWidgetSchema:
    finished = stats.success + stats.error
    return RunsLast24hWidgetSchema(
        generated_at=generated_at,
        window_start=stats.window_start,
        window_end=stats.window_end,
        bucket_minutes=stats.bucket_minutes,
        total=stats.total,
        success=stats.success,
        error=stats.error,
        cancelled=stats.cancelled,
        running=stats.running,
        success_ratio=(stats.success / finished) if finished else None,
        buckets=[
            RunsBucketSchema(
                start=bucket.start,
                total=bucket.total,
                success=bucket.success,
                error=bucket.error,
                cancelled=bucket.cancelled,
                running=bucket.running,
            )
            for bucket in stats.buckets
        ],
    )


@router.get(
    "/runs-24h",
    response_model=RunsLast24hWidgetSchema,
    summary="Виджет: запуски за последние 24 часа",
)
async def get_runs_last_24h_widget(
        session: AsyncSessionDepends,
        user: UserAccessOnly,
) -> RunsLast24hWidgetSchema:
    access_scope = get_access_scope(user)
    now = datetime.now(UTC)
    window_start, window_end = compute_hourly_window(now, hours=RUNS_WINDOW_HOURS)
    stats = await get_runs_window_stats(
        session,
        window_start=window_start,
        window_end=window_end,
        organization_id=access_scope.organization_id,
        owner_user_id=access_scope.owner_user_id,
    )
    return _to_runs_schema(stats, generated_at=now)


# --- Ближайшие запуски по расписанию ---


def _schedule_last_run(runs: list[TaskReadModel]) -> tuple[TaskExecutionStatus | None, datetime | None]:
    if not runs:
        return None, None
    last_run = runs[0]
    return last_run.status, _ensure_utc(last_run.started_at or last_run.queued_at)


@router.get(
    "/scheduled-runs",
    response_model=ScheduledRunsWidgetSchema,
    summary="Виджет: ближайшие запуски по расписанию",
)
async def get_scheduled_runs_widget(
        session: AsyncSessionDepends,
        user: UserAdminAccess,
        scheduler_client: SchedulerClientDepends,
        limit: LimitQuery = 5,
) -> ScheduledRunsWidgetSchema:
    now = datetime.now(UTC)
    organization_id = None if user_has_global_access(user) else user.organization_id
    schedules: list[ProjectScheduleResponse] = await scheduler_client.get_scheduled_projects(
        organization_id=organization_id,
    )

    access_scope = get_access_scope(user)
    projects = await _get_visible_projects(
        session,
        project_ids=[schedule.project_id for schedule in schedules],
        access_scope=access_scope,
    )
    visible = [schedule for schedule in schedules if schedule.project_id in projects]
    upcoming = sorted(
        (
            schedule for schedule in visible
            if not schedule.disabled and schedule.next_run_time is not None
        ),
        key=lambda schedule: _ensure_utc(schedule.next_run_time),
    )[:limit]

    runs_by_project_id = await get_recent_scheduler_runs_by_project_ids(
        session,
        project_ids=[schedule.project_id for schedule in upcoming],
        organization_id=access_scope.organization_id,
        owner_user_id=access_scope.owner_user_id,
        per_project_limit=1,
    )

    items = []
    for schedule in upcoming:
        last_run_status, last_run_time = _schedule_last_run(
            runs_by_project_id.get(schedule.project_id, [])
        )
        items.append(
            ScheduledRunItemSchema(
                project_id=schedule.project_id,
                project_name=projects[schedule.project_id].name,
                cron=schedule.cron,
                next_run_time=_ensure_utc(schedule.next_run_time),
                last_run_status=last_run_status,
                last_run_time=last_run_time,
            )
        )

    return ScheduledRunsWidgetSchema(
        generated_at=now,
        total_schedules=len(visible),
        disabled_schedules=sum(1 for schedule in visible if schedule.disabled),
        items=items,
    )


# --- Сервисы ---


async def _timed_call[T](
        name: str,
        call: Callable[[], Awaitable[T]],
) -> tuple[T | None, float | None]:
    """Run a service probe with a timeout; return (result, latency_ms) or (None, None)."""
    started = time.perf_counter()
    try:
        result = await asyncio.wait_for(call(), timeout=SERVICE_CALL_TIMEOUT_SEC)
    except Exception as exc:  # любой сбой сервиса означает offline
        logger.warning("Widget services probe failed for {}: {}", name, exc)
        return None, None
    return result, (time.perf_counter() - started) * 1000


@router.get(
    "/services",
    response_model=ServicesWidgetSchema,
    summary="Виджет: состояние сервисов",
)
async def get_services_widget(
        _user: UserAdminAccess,
        orchestrator_client: OrchestratorClientDepends,
        scheduler_client: SchedulerClientDepends,
        sys_info: Annotated[SystemInfo, Depends(get_sys_info)],
) -> ServicesWidgetSchema:
    now = datetime.now(UTC)
    (workers, orchestrator_latency), (scheduler_info, scheduler_latency) = await asyncio.gather(
        _timed_call("orchestrator", orchestrator_client.get_system_stats),
        _timed_call("project_scheduler", scheduler_client.system_status),
    )
    worker_list: list[WorkerSystemInfo] = workers or []

    services = [
        ServiceStatusItemSchema(
            name="gateway",
            status=WorkerStatus.ONLINE,
            latency_ms=None,
            uptime_seconds=sys_info.app_uptime_seconds,
        ),
        ServiceStatusItemSchema(
            name="project_scheduler",
            status=WorkerStatus.ONLINE if scheduler_info is not None else WorkerStatus.OFFLINE,
            latency_ms=scheduler_latency,
            uptime_seconds=scheduler_info.app_uptime_seconds if scheduler_info else None,
        ),
        ServiceStatusItemSchema(
            name="orchestrator",
            status=WorkerStatus.ONLINE if workers is not None else WorkerStatus.OFFLINE,
            latency_ms=orchestrator_latency,
            uptime_seconds=None,
        ),
    ]
    return ServicesWidgetSchema(
        generated_at=now,
        system_state=get_system_state_monitor().snapshot.state,
        services=services,
        workers=WorkersSummarySchema(
            total=len(worker_list),
            online=sum(1 for worker in worker_list if worker.status == WorkerStatus.ONLINE),
            busy=sum(1 for worker in worker_list if worker.has_running_task),
        ),
    )


# --- Проблемные проекты ---


def _count_consecutive_failures(runs: list[TaskReadModel]) -> int:
    """Leading ERROR runs in a newest-first list; cancelled and in-flight runs are skipped."""
    streak = 0
    for run in runs:
        if run.status not in TERMINAL_STATUSES or run.status is TaskExecutionStatus.CANCELLED:
            continue
        if run.status is not TaskExecutionStatus.ERROR:
            break
        streak += 1
    return streak


def _to_failing_project_schema(
        stats: ProjectErrorStats,
        *,
        project: ProjectRecord,
        recent_runs: list[TaskReadModel],
) -> FailingProjectItemSchema:
    return FailingProjectItemSchema(
        project_id=stats.project_id,
        project_name=project.name,
        error_count=stats.error_count,
        total_count=stats.total_count,
        last_error_at=stats.last_error_at,
        consecutive_failures=_count_consecutive_failures(recent_runs),
    )


@router.get(
    "/failing-projects",
    response_model=FailingProjectsWidgetSchema,
    summary="Виджет: проблемные проекты за 7 дней",
)
async def get_failing_projects_widget(
        session: AsyncSessionDepends,
        user: UserAccessOnly,
        limit: LimitQuery = 5,
) -> FailingProjectsWidgetSchema:
    now = datetime.now(UTC)
    window_start = now - timedelta(days=FAILING_PROJECTS_WINDOW_DAYS)
    access_scope = get_access_scope(user)

    stats = await get_project_error_stats(
        session,
        since=window_start,
        organization_id=access_scope.organization_id,
        owner_user_id=access_scope.owner_user_id,
        limit=limit,
    )
    project_ids = [item.project_id for item in stats]
    projects = await _get_visible_projects(
        session,
        project_ids=project_ids,
        access_scope=access_scope,
    )
    recent_runs = await get_recent_project_runs_by_project_ids(
        session,
        project_ids=[project_id for project_id in project_ids if project_id in projects],
        organization_id=access_scope.organization_id,
        owner_user_id=access_scope.owner_user_id,
        per_project_limit=FAILING_PROJECTS_STREAK_DEPTH,
    )

    return FailingProjectsWidgetSchema(
        generated_at=now,
        window_start=window_start,
        window_end=now,
        items=[
            _to_failing_project_schema(
                item,
                project=projects[item.project_id],
                recent_runs=recent_runs.get(item.project_id, []),
            )
            for item in stats
            if item.project_id in projects
        ],
    )
