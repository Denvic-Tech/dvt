from typing import Any

from apscheduler.triggers.cron import CronTrigger
from fastapi import HTTPException

from src.clients.scheduler_client import SchedulerClient
from src.modules.project.infra.queries import (
    get_recent_scheduler_runs_by_project_ids,
    task_read_to_project_schedule_run,
)
from src.schemas.internal.project_scheduler import (
    ProjectSchedulePatchRequest,
    ProjectScheduleRequest,
)
from src.utils.access_control import get_access_scope
from src.utils.user_roles import user_has_admin_access

from .access import get_accessible_project, list_accessible_projects
from .auth import MCPPrincipal
from .errors import AIMCPHTTPError
from .pagination import decode_cursor, encode_cursor
from .redaction import redact_log_message
from .tasks import _check_execution_connections

SCHEDULE_FIELDS = frozenset(ProjectScheduleRequest.model_fields) - {"project_id", "mode"}


def _require_admin(principal: MCPPrincipal) -> None:
    if not user_has_admin_access(principal.user):
        raise AIMCPHTTPError(403, "SCOPE_DENIED", "Schedules require an administrator role.")


async def _scheduler_call(method: str, **kwargs):
    try:
        async with SchedulerClient() as client:
            return await getattr(client, method)(**kwargs)
    except HTTPException as exc:
        if exc.status_code == 404:
            raise AIMCPHTTPError(
                404, "SCHEDULE_NOT_FOUND", "Project schedule does not exist.",
            ) from exc
        if exc.status_code in {400, 422}:
            raise AIMCPHTTPError(
                422, "INVALID_ARGUMENTS", "Schedule settings are invalid.",
            ) from exc
        raise AIMCPHTTPError(
            503, "SCHEDULER_UNAVAILABLE", "Scheduler service is unavailable.",
        ) from exc
    except TimeoutError as exc:
        raise AIMCPHTTPError(
            503, "SCHEDULER_UNAVAILABLE", "Scheduler service is unavailable.",
        ) from exc


async def _schedules(principal: MCPPrincipal):
    scope = get_access_scope(principal.user)
    return await _scheduler_call(
        "get_scheduled_projects", organization_id=scope.organization_id,
    )


async def _current_schedule(*, session, principal: MCPPrincipal, project_id: str):
    _require_admin(principal)
    await get_accessible_project(session, principal, project_id)
    return next(
        (item for item in await _schedules(principal) if item.project_id == project_id), None,
    )


def _require_schedule(schedule):
    if schedule is None:
        raise AIMCPHTTPError(404, "SCHEDULE_NOT_FOUND", "Project schedule does not exist.")
    return schedule


async def _with_history(*, session, principal: MCPPrincipal, schedules: list) -> list[dict]:
    if not schedules:
        return []
    scope = get_access_scope(principal.user)
    runs = await get_recent_scheduler_runs_by_project_ids(
        session,
        project_ids=[item.project_id for item in schedules],
        organization_id=scope.organization_id,
        owner_user_id=scope.owner_user_id,
        per_project_limit=10,
    )
    result = []
    for schedule in schedules:
        recent = [
            task_read_to_project_schedule_run(task)
            for task in runs.get(schedule.project_id, [])
        ]
        payload = schedule.model_dump(mode="json", exclude={"mode"})
        payload["recent_runs"] = [run.model_dump(mode="json") for run in recent]
        if recent:
            last = payload["recent_runs"][0]
            payload.update(
                last_run_task_id=last["task_id"],
                last_run_status=last["status"],
                last_run_time=last["started_at"] or last["queued_at"],
                last_run_message=last["message"],
                last_run_termination_reason=last["termination_reason"],
            )
        payload["last_run_message"] = redact_log_message(payload.get("last_run_message"))
        for run in payload["recent_runs"]:
            run["message"] = redact_log_message(run.get("message"))
        if payload.get("latest_run_chain"):
            chain = payload["latest_run_chain"]
            chain["last_error"] = redact_log_message(chain.get("last_error"))
        result.append(payload)
    return result


async def list_project_schedules(
    *, session, principal: MCPPrincipal, cursor: str | None = None, limit: int = 50,
) -> dict:
    _require_admin(principal)
    offset = decode_cursor(cursor)
    limit = max(1, min(limit, 200))
    projects = await list_accessible_projects(session, principal)
    allowed = {project.id for project in projects}
    schedules = sorted(
        (item for item in await _schedules(principal) if item.project_id in allowed),
        key=lambda item: item.project_id,
    ) if allowed else []
    page = schedules[offset:offset + limit]
    return {
        "items": await _with_history(session=session, principal=principal, schedules=page),
        "next_cursor": encode_cursor(offset + len(page), len(schedules)),
    }


async def get_project_schedule(*, session, principal: MCPPrincipal, project_id: str) -> dict:
    schedule = await _current_schedule(
        session=session, principal=principal, project_id=project_id,
    )
    items = await _with_history(
        session=session, principal=principal, schedules=[schedule] if schedule else [],
    )
    return {"schedule": items[0] if items else None}


async def set_project_schedule(
    *, session, principal: MCPPrincipal, project_id: str, cron: str,
    force_exec: bool = False, max_retries: int = 0,
    retry_delay_seconds: int = 60, retry_backoff: str = "fixed",
    retry_max_delay_seconds: int = 3600,
) -> dict:
    _require_admin(principal)
    await get_accessible_project(session, principal, project_id)
    request = ProjectScheduleRequest(
        project_id=project_id, cron=cron, mode="full", force_exec=force_exec,
        max_retries=max_retries, retry_delay_seconds=retry_delay_seconds,
        retry_backoff=retry_backoff, retry_max_delay_seconds=retry_max_delay_seconds,
    )
    CronTrigger.from_crontab(request.cron, timezone="UTC")
    await _check_execution_connections(
        session=session, principal=principal, project_id=project_id, target_node_ids=None,
    )
    payload = request.model_dump(mode="json")
    payload["scheduled_by_user_id"] = principal.user.id
    result = await _scheduler_call("schedule_project", data=payload)
    return result.model_dump(mode="json")


async def update_project_schedule(
    *, session, principal: MCPPrincipal, project_id: str, patch: dict[str, Any],
) -> dict:
    schedule = _require_schedule(await _current_schedule(
        session=session, principal=principal, project_id=project_id,
    ))
    if (
        not isinstance(patch, dict) or not patch
        or patch.keys() - SCHEDULE_FIELDS or any(value is None for value in patch.values())
    ):
        raise AIMCPHTTPError(
            422, "INVALID_ARGUMENTS", "Provide non-null schedule settings to change.",
        )
    # Validate the merged retry policy as well as each explicitly supplied field.
    merged = ProjectScheduleRequest.model_validate({
        **schedule.model_dump(include=set(ProjectScheduleRequest.model_fields)),
        **patch, "mode": "full",
    })
    CronTrigger.from_crontab(merged.cron, timezone="UTC")
    request = ProjectSchedulePatchRequest.model_validate({**patch, "mode": "full"})
    if not schedule.disabled:
        await _check_execution_connections(
            session=session, principal=principal, project_id=project_id, target_node_ids=None,
        )
    payload = request.model_dump(mode="json", exclude_unset=True)
    payload["scheduled_by_user_id"] = principal.user.id
    result = await _scheduler_call(
        "patch_project_schedule", project_id=project_id, data=payload,
    )
    return result.model_dump(mode="json")


async def set_project_schedule_enabled(
    *, session, principal: MCPPrincipal, project_id: str, enabled: bool,
) -> dict:
    schedule = _require_schedule(await _current_schedule(
        session=session, principal=principal, project_id=project_id,
    ))
    if not isinstance(enabled, bool):
        raise AIMCPHTTPError(422, "INVALID_ARGUMENTS", "enabled must be a boolean.")
    if enabled:
        CronTrigger.from_crontab(schedule.cron, timezone="UTC")
        await _check_execution_connections(
            session=session, principal=principal, project_id=project_id, target_node_ids=None,
        )
    payload = {"disabled": not enabled, "scheduled_by_user_id": principal.user.id}
    if enabled:
        payload["mode"] = "full"
    result = await _scheduler_call(
        "patch_project_schedule", project_id=project_id, data=payload,
    )
    return result.model_dump(mode="json")
