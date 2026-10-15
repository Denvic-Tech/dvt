from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.modules.task_execution.domain.types import TaskExecutionStatus, TaskTerminationReason

ERROR = TaskExecutionStatus.ERROR
SUCCESS = TaskExecutionStatus.SUCCESS


@pytest.mark.asyncio
async def test_failing_projects_empty(gateway_client, router_prefix, test_user, test_user_project, add_task):
    add_task(user=test_user, project=test_user_project, queued_at=datetime.now(UTC) - timedelta(hours=1))

    resp = await gateway_client.get(f"{router_prefix}/widgets/failing-projects")

    assert resp.status_code == 200, resp.json()
    payload = resp.json()
    assert payload["items"] == []
    assert datetime.fromisoformat(payload["window_end"]) - datetime.fromisoformat(
        payload["window_start"]
    ) == timedelta(days=7)


@pytest.mark.asyncio
async def test_failing_projects_ranking_window_and_streak(
        gateway_client,
        router_prefix,
        test_user,
        create_project,
        add_task,
):
    now = datetime.now(UTC)
    worst = create_project(user=test_user, name="Worst")
    recent_single = create_project(user=test_user, name="Recent single")
    old_single = create_project(user=test_user, name="Old single")
    healthy = create_project(user=test_user, name="Healthy")
    expired = create_project(user=test_user, name="Expired")

    # worst: SUCCESS, ERROR, ERROR (old → new) → streak 2, errors 2, total 3
    add_task(user=test_user, project=worst, queued_at=now - timedelta(days=3), status=SUCCESS)
    add_task(user=test_user, project=worst, queued_at=now - timedelta(days=2), status=ERROR)
    add_task(user=test_user, project=worst, queued_at=now - timedelta(days=1), status=ERROR)
    # recent_single: ERROR, then a cancelled run (skipped for streak) → streak 1
    add_task(user=test_user, project=recent_single, queued_at=now - timedelta(hours=5), status=ERROR)
    add_task(
        user=test_user,
        project=recent_single,
        queued_at=now - timedelta(hours=4),
        status=TaskExecutionStatus.CANCELLED,
        termination_reason=TaskTerminationReason.USER_STOP.value,
    )
    # old_single: ERROR, then SUCCESS → streak 0
    add_task(user=test_user, project=old_single, queued_at=now - timedelta(days=6), status=ERROR)
    add_task(user=test_user, project=old_single, queued_at=now - timedelta(days=5), status=SUCCESS)
    add_task(user=test_user, project=healthy, queued_at=now - timedelta(hours=1), status=SUCCESS)
    add_task(user=test_user, project=expired, queued_at=now - timedelta(days=8), status=ERROR)

    resp = await gateway_client.get(f"{router_prefix}/widgets/failing-projects")

    assert resp.status_code == 200, resp.json()
    items = resp.json()["items"]
    assert [item["project_name"] for item in items] == ["Worst", "Recent single", "Old single"]
    assert [item["error_count"] for item in items] == [2, 1, 1]
    assert [item["total_count"] for item in items] == [3, 2, 2]
    assert [item["consecutive_failures"] for item in items] == [2, 1, 0]
    assert datetime.fromisoformat(items[0]["last_error_at"]) == pytest.approx(
        now - timedelta(days=1), abs=timedelta(seconds=1)
    )


@pytest.mark.asyncio
async def test_failing_projects_limit_and_deleted_project(
        gateway_client,
        router_prefix,
        test_user,
        create_project,
        add_task,
):
    now = datetime.now(UTC)
    deleted = create_project(user=test_user, name="Deleted", is_deleted=True)
    alive = create_project(user=test_user, name="Alive")
    for _ in range(3):
        add_task(user=test_user, project=deleted, queued_at=now - timedelta(hours=1), status=ERROR)
    add_task(user=test_user, project=alive, queued_at=now - timedelta(hours=1), status=ERROR)

    resp = await gateway_client.get(f"{router_prefix}/widgets/failing-projects", params={"limit": 1})

    assert resp.status_code == 200
    # удалённый проект занимает место в выборке, но в ответ не попадает
    assert resp.json()["items"] == []

    resp = await gateway_client.get(f"{router_prefix}/widgets/failing-projects", params={"limit": 5})
    assert [item["project_name"] for item in resp.json()["items"]] == ["Alive"]


@pytest.mark.asyncio
async def test_failing_projects_scope_isolation(
        gateway_client,
        router_prefix,
        test_user,
        test_user_project,
        test_admin_user,
        create_user,
        create_project,
        add_task,
        set_current_user,
):
    now = datetime.now(UTC)
    colleague = create_user(organization_id=test_user.organization_id)
    colleague_project = create_project(user=colleague, name="Colleague")
    add_task(user=test_user, project=test_user_project, queued_at=now - timedelta(hours=1), status=ERROR)
    add_task(user=colleague, project=colleague_project, queued_at=now - timedelta(hours=1), status=ERROR)

    own = (await gateway_client.get(f"{router_prefix}/widgets/failing-projects")).json()
    assert [item["project_id"] for item in own["items"]] == [test_user_project.id]

    set_current_user(test_admin_user)
    org_wide = (await gateway_client.get(f"{router_prefix}/widgets/failing-projects")).json()
    assert {item["project_id"] for item in org_wide["items"]} == {test_user_project.id, colleague_project.id}
