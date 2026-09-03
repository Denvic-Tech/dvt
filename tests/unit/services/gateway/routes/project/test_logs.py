from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from src.models import LogRecord
from src.modules.task_execution.domain.types import TaskExecutionStatus, TaskSource
from src.modules.task_execution.infra.db_models import TaskRecord
from src.pipeline.execution_mode import PipelineExecutionMode


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _create_task(db_session, *, project, user, task_id: str | None = None) -> TaskRecord:
    task = TaskRecord(
        task_id=task_id or str(uuid4()),
        project_id=project.id,
        user_id=user.id,
        organization_id=project.organization_id,
        mode=PipelineExecutionMode.FULL,
        force_exec=False,
        status=TaskExecutionStatus.SUCCESS,
        source=TaskSource.UI,
        queued_at=_now(),
        updated_at=_now(),
    )
    db_session.add(task)
    db_session.commit()
    db_session.refresh(task)
    return task


def _create_log(
        db_session,
        *,
        task_id: str,
        user_id: str,
        message: str,
        created_at: datetime,
        level: str = "INFO",
) -> LogRecord:
    entry = LogRecord(
        id=str(uuid4()),
        created_at=created_at,
        level=level,
        service_name="gateway-test",
        message=message,
        user_id=user_id,
        task_id=task_id,
        logger_name="test.logger",
        module="tests.project.logs",
        function="test_logs",
        line=42,
    )
    db_session.add(entry)
    db_session.commit()
    db_session.refresh(entry)
    return entry


@pytest.mark.asyncio
async def test_get_project_logs_returns_paginated_entries(
        gateway_client,
        router_prefix,
        db_session,
        test_user,
        test_user_project,
):
    task = _create_task(
        db_session,
        project=test_user_project,
        user=test_user,
    )
    base_time = _now()
    older = _create_log(
        db_session,
        task_id=task.task_id,
        user_id=test_user.id,
        message="older log",
        created_at=base_time - timedelta(minutes=2),
    )
    newer = _create_log(
        db_session,
        task_id=task.task_id,
        user_id=test_user.id,
        message="newer log",
        created_at=base_time - timedelta(minutes=1),
        level="ERROR",
    )

    response = await gateway_client.get(
        f"{router_prefix}/projects/{test_user_project.id}/logs",
        params={"task_id": task.task_id, "limit": 10, "offset": 0},
    )

    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["total"] == 2
    assert payload["limit"] == 10
    assert payload["offset"] == 0
    assert payload["has_more"] is False
    assert [item["message"] for item in payload["items"]] == ["newer log", "older log"]
    assert payload["items"][0]["message"] == "newer log"


@pytest.mark.asyncio
async def test_get_project_logs_pagination_uses_total_and_has_more(
        gateway_client,
        router_prefix,
        db_session,
        test_user,
        test_user_project,
):
    task = _create_task(
        db_session,
        project=test_user_project,
        user=test_user,
    )
    base_time = _now()
    for index in range(3):
        _create_log(
            db_session,
            task_id=task.task_id,
            user_id=test_user.id,
            message=f"log-{index}",
            created_at=base_time - timedelta(minutes=index),
        )

    response = await gateway_client.get(
        f"{router_prefix}/projects/{test_user_project.id}/logs",
        params={"task_id": task.task_id, "limit": 2, "offset": 0},
    )

    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["total"] == 3
    assert len(payload["items"]) == 2
    assert payload["has_more"] is True


@pytest.mark.asyncio
async def test_get_project_logs_returns_empty_page_for_task_without_logs(
        gateway_client,
        router_prefix,
        db_session,
        test_user,
        test_user_project,
):
    task = _create_task(
        db_session,
        project=test_user_project,
        user=test_user,
    )

    response = await gateway_client.get(
        f"{router_prefix}/projects/{test_user_project.id}/logs",
        params={"task_id": task.task_id},
    )

    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["total"] == 0
    assert payload["items"] == []
    assert payload["has_more"] is False


@pytest.mark.asyncio
async def test_get_project_logs_returns_404_for_task_from_other_project(
        gateway_client,
        router_prefix,
        db_session,
        test_user,
        test_user_project,
        test_admin_project,
):
    other_task = _create_task(
        db_session,
        project=test_admin_project,
        user=test_user,
    )

    response = await gateway_client.get(
        f"{router_prefix}/projects/{test_user_project.id}/logs",
        params={"task_id": other_task.task_id},
    )

    assert response.status_code == 404, response.json()
    assert other_task.task_id in response.text


@pytest.mark.asyncio
async def test_get_project_logs_returns_404_for_inaccessible_project(
        gateway_client,
        router_prefix,
        db_session,
        test_admin_user,
        test_admin_project,
):
    task = _create_task(
        db_session,
        project=test_admin_project,
        user=test_admin_user,
    )
    _create_log(
        db_session,
        task_id=task.task_id,
        user_id=test_admin_user.id,
        message="hidden log",
        created_at=_now(),
    )

    response = await gateway_client.get(
        f"{router_prefix}/projects/{test_admin_project.id}/logs",
        params={"task_id": task.task_id},
    )

    assert response.status_code == 404, response.json()
    assert test_admin_project.id in response.text
