from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from usrak.core.dependencies.user import build_user_dependency
from usrak.core.enums import AuthMode

from src.clients.scheduler_client import SchedulerClient, get_schedule_client
from src.crud import project as project_crud
from src.db.fastapi.dependencies import AsyncSessionDepends
from src.db.session import AsyncSession
from src.enums import DVTDefaultRoles
from src.modules.project.infra.http_schemas import ScheduleResponse
from src.modules.project.infra.queries import (
    get_recent_scheduler_runs_by_project_ids,
    task_read_to_project_schedule_run,
)
from src.modules.user.infra.db_models import UserRecord
from src.schemas.internal import (
    ProjectSchedulePatchRequest,
    ProjectScheduleRequest,
    ProjectScheduleResponse,
)
from src.utils.access_control import get_access_scope
from src.utils.user_roles import user_has_global_access

SCHEDULE_HISTORY_LIMIT = 10

router = APIRouter(
    prefix="/scheduler",
    tags=["Project Scheduler"],
)

_get_user = build_user_dependency(
    auth_mode=AuthMode.ACCESS_ONLY,
    require_active=True,
    require_verified=True,
    require_roles=[DVTDefaultRoles.SUPERADMIN, DVTDefaultRoles.ADMIN],
)
UserDepends = Annotated[UserRecord, Depends(_get_user)]


async def _get_accessible_project(
    *,
    project_id: str,
    session: AsyncSession,
    user: UserRecord,
):
    access_scope = get_access_scope(user)
    return (
        await project_crud.get_projects_by(
            session=session,
            organization_id=access_scope.organization_id,
            owner_user_id=access_scope.owner_user_id,
            project_id=project_id,
        )
    ).first()


@router.post("/schedule", response_model=ScheduleResponse)
async def schedule(
    request: ProjectScheduleRequest,
    session: AsyncSessionDepends,
    user: UserDepends,
    schedule_client: Annotated[SchedulerClient, Depends(get_schedule_client)],
):
    project = await _get_accessible_project(
        project_id=request.project_id,
        session=session,
        user=user,
    )

    if not project:
        raise HTTPException(
            status_code=404,
            detail=f"Project with ID {request.project_id} not found",
        )

    payload = request.model_dump(mode="json", exclude_none=True)
    payload["scheduled_by_user_id"] = user.id
    return await schedule_client.schedule_project(data=payload)


@router.patch("/schedule/{project_id}", response_model=ScheduleResponse)
async def patch_schedule(
    project_id: str,
    request: ProjectSchedulePatchRequest,
    session: AsyncSessionDepends,
    user: UserDepends,
    scheduler_client: Annotated[SchedulerClient, Depends(get_schedule_client)],
):
    project = await _get_accessible_project(
        project_id=project_id,
        session=session,
        user=user,
    )

    if not project:
        raise HTTPException(
            status_code=404,
            detail=f"Project with ID {project_id} not found",
        )

    payload = request.model_dump(mode="json", exclude_unset=True)
    payload["scheduled_by_user_id"] = user.id
    return await scheduler_client.patch_project_schedule(project_id=project_id, data=payload)


@router.post("/unschedule", response_model=ScheduleResponse)
async def unschedule(
    project_id: str,
    session: AsyncSessionDepends,
    user: UserDepends,
    scheduler_client: Annotated[SchedulerClient, Depends(get_schedule_client)],
):
    project = await _get_accessible_project(
        project_id=project_id,
        session=session,
        user=user,
    )

    if not project:
        raise HTTPException(
            status_code=404,
            detail=f"Project with ID {project_id} not found",
        )

    return await scheduler_client.unschedule_project(project_id)


@router.delete("/schedule/{project_id}", response_model=ScheduleResponse)
async def delete_schedule(
    project_id: str,
    session: AsyncSessionDepends,
    user: UserDepends,
    scheduler_client: Annotated[SchedulerClient, Depends(get_schedule_client)],
):
    project = await _get_accessible_project(
        project_id=project_id,
        session=session,
        user=user,
    )

    if not project:
        raise HTTPException(
            status_code=404,
            detail=f"Project with ID {project_id} not found",
        )

    return await scheduler_client.delete_project_schedule(project_id)


@router.get("/scheduled", response_model=list[ProjectScheduleResponse])
async def get_scheduled_projects(
    session: AsyncSessionDepends,
    user: UserDepends,
    scheduler_client: Annotated[SchedulerClient, Depends(get_schedule_client)],
):
    organization_id = None if user_has_global_access(user) else user.organization_id
    schedules = await scheduler_client.get_scheduled_projects(organization_id=organization_id)
    if not schedules:
        return schedules

    access_scope = get_access_scope(user)
    runs_by_project_id = await get_recent_scheduler_runs_by_project_ids(
        session,
        project_ids=[schedule.project_id for schedule in schedules],
        organization_id=access_scope.organization_id,
        owner_user_id=access_scope.owner_user_id,
        per_project_limit=SCHEDULE_HISTORY_LIMIT,
    )

    for schedule in schedules:
        recent_runs = [
            task_read_to_project_schedule_run(task)
            for task in runs_by_project_id.get(schedule.project_id, [])
        ]
        schedule.recent_runs = recent_runs
        if not recent_runs:
            continue

        last_run = recent_runs[0]
        schedule.last_run_task_id = last_run.task_id
        schedule.last_run_status = last_run.status
        schedule.last_run_time = last_run.started_at or last_run.queued_at
        schedule.last_run_message = last_run.message
        schedule.last_run_termination_reason = last_run.termination_reason

    return schedules
