from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from typing import Any, Literal

from src import enums
from src.crud import project as project_crud
from src.crud.admin import user as user_crud
from src.db import AsyncSessionLocal
from src.infra.orchestrator_commands import publish_orchestrator_command
from src.modules.task_execution.domain.types import TaskExecutionStatus, TaskSource
from src.modules.task_execution.facade import build_task_lifecycle_commands
from src.modules.task_execution.infra.queries import get_task_by_id
from src.modules.task_execution.infra.transport import NestedTaskEnqueueCommand, TaskInternal
from src.node_dsl.variables import build_variable_output, is_unresolved_value
from src.runtime.async_runtime import shared_orchestrator
from src.schemas.http.project_variable import ProjectVariableBase
from src.utils.access_control import get_access_scope

UnresolvedVariablesPolicy = Literal["error", "skip"]
SystemVariablesPolicy = Literal["error", "skip", "include"]


def _build_nested_task_variable_overrides(
    variables: Mapping[str, Any] | None,
    *,
    unresolved_variables_policy: UnresolvedVariablesPolicy,
    system_variables_policy: SystemVariablesPolicy,
) -> dict[str, ProjectVariableBase] | None:
    if unresolved_variables_policy not in {"error", "skip"}:
        raise ValueError(
            f"Unsupported unresolved_variables_policy: {unresolved_variables_policy}"
        )
    if system_variables_policy not in {"error", "skip", "include"}:
        raise ValueError(f"Unsupported system_variables_policy: {system_variables_policy}")

    overrides: dict[str, ProjectVariableBase] = {}
    for variable_name, payload in (variables or {}).items():
        variable = build_variable_output(variable_name, payload)

        if is_unresolved_value(variable.value):
            if unresolved_variables_policy == "skip":
                continue
            reason = variable.value.reason or "unknown reason"
            raise ValueError(
                f"Cannot pass unresolved variable '{variable_name}' to a child project: {reason}"
            )

        if variable.var_type == "system":
            if system_variables_policy == "skip":
                continue
            if system_variables_policy == "error":
                raise ValueError(
                    f"Cannot pass system variable '{variable_name}' to a child project "
                    "with system_variables_policy='error'"
                )

        overrides[variable_name] = ProjectVariableBase(
            type=variable.type,
            value=variable.value,
            is_list_type=variable.is_list_type,
        )

    return overrides or None


async def enqueue_project_task_for_node(
    *,
    actor_user_id: str,
    target_project_id: str,
    parent_project_id: str,
    parent_task_id: str,
    wait_for_completion: bool,
    force_exec: bool,
    send_ws_messages: bool = True,
    variables: Mapping[str, Any] | None = None,
    unresolved_variables_policy: UnresolvedVariablesPolicy = "error",
    system_variables_policy: SystemVariablesPolicy = "error",
) -> TaskInternal:
    from src.infra.task import build_pending_task_from_project
    from src.utils.worker_id import get_worker_id

    if wait_for_completion and target_project_id == parent_project_id:
        raise ValueError(
            f"Nested wait is not allowed for the same project: {target_project_id}. "
            f"parent_task_id={parent_task_id}"
        )

    async with AsyncSessionLocal() as session:
        actor_user = (
            await user_crud.get_users_by(
                session=session,
                user_id=actor_user_id,
                is_active=True,
                is_verified=True,
                limit=1,
            )
        ).first()
        if actor_user is None:
            raise user_crud.UserNotFoundException(f"User not found: {actor_user_id}")

        access_scope = get_access_scope(actor_user)
        target_project = (
            await project_crud.get_projects_by(
                session=session,
                organization_id=access_scope.organization_id,
                owner_user_id=access_scope.owner_user_id,
                project_id=target_project_id,
            )
        ).first()
        if target_project is None:
            raise project_crud.ProjectNotFoundException(f"Project not found: {target_project_id}")

        variable_overrides = _build_nested_task_variable_overrides(
            variables,
            unresolved_variables_policy=unresolved_variables_policy,
            system_variables_policy=system_variables_policy,
        )
        child_task = await build_pending_task_from_project(
            project=target_project,
            send_ws_messages=send_ws_messages,
            force_exec=force_exec,
            variables=variable_overrides,
            source=TaskSource.NODE,
            user=actor_user,
            session=session,
        )
        try:
            await publish_orchestrator_command(
                NestedTaskEnqueueCommand(
                    request_id=child_task.task_id,
                    task=child_task,
                    origin_worker_id=get_worker_id(),
                    parent_task_id=parent_task_id,
                    parent_project_id=parent_project_id,
                    wait_for_completion=wait_for_completion,
                )
            )
        except Exception:
            lifecycle = build_task_lifecycle_commands()
            await lifecycle.fail_pending_execution.execute(
                task_id=child_task.task_id,
                message="Failed nested task queue",
            )
            raise
        return child_task


async def wait_for_task_terminal_state(
    *,
    child_task_id: str,
    poll_interval_sec: float = 1.0,
    timeout_sec: float | None = None,
    cancel_on_timeout: bool = False,
) -> TaskExecutionStatus:
    child_task_id = child_task_id.strip()
    if not child_task_id:
        raise ValueError("child_task_id is empty")
    if poll_interval_sec <= 0:
        raise ValueError("poll_interval_sec must be positive")
    if timeout_sec is not None and timeout_sec <= 0:
        raise ValueError("timeout_sec must be positive")

    started_at = time.monotonic()
    while True:
        async with AsyncSessionLocal() as session:
            task_entry = await get_task_by_id(session, task_id=child_task_id)

        if task_entry is None:
            raise RuntimeError(f"Task not found: {child_task_id}")

        if task_entry.status == TaskExecutionStatus.SUCCESS:
            return task_entry.status

        if task_entry.status == TaskExecutionStatus.ERROR:
            message = task_entry.message or "Child task finished with ERROR status"
            raise RuntimeError(f"Child task {child_task_id} failed: {message}")

        if task_entry.status == TaskExecutionStatus.CANCELLED:
            reason = task_entry.termination_reason or "unknown"
            raise RuntimeError(f"Child task {child_task_id} was cancelled: {reason}")

        if timeout_sec is not None and (time.monotonic() - started_at) >= timeout_sec:
            if cancel_on_timeout:
                orchestrator = await shared_orchestrator.get()
                await orchestrator.cancel_task(task_id=child_task_id)
            raise TimeoutError(
                f"Timed out while waiting for child task {child_task_id} "
                f"after {timeout_sec} seconds"
            )

        await asyncio.sleep(poll_interval_sec)
