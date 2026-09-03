from fastapi import APIRouter, Depends

from services.project_scheduler.deps import ProjectSchedulerManager, get_project_scheduler_manager

from src.modules.project.infra.http_schemas import ScheduleResponse
from src.schemas.internal.project_scheduler import (
    ProjectSchedulePatchRequest,
    ProjectScheduleResponse,
    ProjectScheduleServiceRequest,
)

router = r = APIRouter(
    prefix="/projects",
    tags=["Tasks"],
)


@r.post("/schedule", response_model=ScheduleResponse)
async def schedule(
        project: ProjectScheduleServiceRequest,
        project_scheduler_manager: ProjectSchedulerManager = Depends(get_project_scheduler_manager),
):
    """
    Запланировать выполнение проекта по расписанию (crontab)
    """

    await project_scheduler_manager.schedule_project(
        project_id=project.project_id,
        cron=project.cron,
        scheduled_by_user_id=project.scheduled_by_user_id,
        mode=project.mode,
        force_exec=project.force_exec,
        max_retries=project.max_retries,
        retry_delay_seconds=project.retry_delay_seconds,
        retry_backoff=project.retry_backoff,
        retry_max_delay_seconds=project.retry_max_delay_seconds,
    )

    return ScheduleResponse(
        success=True,
        message=f"Project scheduled with cron '{project.cron}'",
        project_id=project.project_id
    )


@r.patch("/schedule/{project_id}", response_model=ScheduleResponse)
async def patch_schedule(
        project_id: str,
        patch: ProjectSchedulePatchRequest,
        project_scheduler_manager: ProjectSchedulerManager = Depends(get_project_scheduler_manager),
):
    """
    Частично обновить существующее расписание выполнения проекта
    """

    await project_scheduler_manager.patch_project_schedule(project_id=project_id, patch=patch)

    return ScheduleResponse(
        success=True,
        message="Project schedule updated",
        project_id=project_id
    )


@r.post("/unschedule/{project_id}", response_model=ScheduleResponse)
async def unschedule(
        project_id: str,
        project_scheduler_manager: ProjectSchedulerManager = Depends(get_project_scheduler_manager),
):
    """
    Удалить расписание проекта
    """

    await project_scheduler_manager.unschedule_project(project_id)

    return ScheduleResponse(
        success=True,
        message=f"Project unscheduled",
        project_id=project_id
    )


@r.delete("/schedule/{project_id}", response_model=ScheduleResponse)
async def delete_schedule(
        project_id: str,
        project_scheduler_manager: ProjectSchedulerManager = Depends(get_project_scheduler_manager),
):
    """
    Полностью удалить расписание проекта
    """

    await project_scheduler_manager.delete_project_schedule(project_id)

    return ScheduleResponse(
        success=True,
        message="Project schedule deleted",
        project_id=project_id
    )


@r.get("/scheduled/", response_model=list[ProjectScheduleResponse])
async def get_scheduled_projects(
        organization_id: str | None = None,
        scheduler_manager: ProjectSchedulerManager = Depends(get_project_scheduler_manager),
):
    """
    Список расписаний проектов
    """
    return await scheduler_manager.get_scheduled_projects(organization_id=organization_id)
