from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.enums import DVTDefaultRoles
from src.modules.task_execution.domain.types import (
    TaskExecutionStatus,
    TaskSource,
    TaskTerminationReason,
)
from src.modules.task_execution.infra.queries import aggregate_runs, compute_hourly_window
from src.pipeline.execution_mode import PipelineExecutionMode

NOW = datetime(2026, 10, 14, 14, 37, 12, tzinfo=UTC)


def test_compute_hourly_window_is_hour_aligned():
    window_start, window_end = compute_hourly_window(NOW)

    assert window_start == datetime(2026, 10, 13, 15, 0, tzinfo=UTC)
    assert window_end == NOW


def test_aggregate_runs_assigns_buckets_and_clamps_last_partial_bucket():
    window_start, window_end = compute_hourly_window(NOW)
    rows = [
        (window_start, TaskExecutionStatus.SUCCESS),
        (window_start + timedelta(minutes=59, seconds=59), TaskExecutionStatus.SUCCESS),
        (window_start + timedelta(hours=1), TaskExecutionStatus.SUCCESS),
        (window_end, TaskExecutionStatus.SUCCESS),
    ]

    stats = aggregate_runs(rows, window_start=window_start, window_end=window_end)

    assert len(stats.buckets) == 24
    assert [bucket.start for bucket in stats.buckets] == [
        window_start + timedelta(hours=index) for index in range(24)
    ]
    assert stats.buckets[0].total == 2
    assert stats.buckets[1].total == 1
    assert stats.buckets[23].total == 1
    assert stats.bucket_minutes == 60


def test_aggregate_runs_counts_statuses_and_keeps_invariant():
    window_start, window_end = compute_hourly_window(NOW)
    rows = [(window_start + timedelta(hours=2), status) for status in TaskExecutionStatus]

    stats = aggregate_runs(rows, window_start=window_start, window_end=window_end)

    assert stats.success == 1
    assert stats.error == 1
    assert stats.cancelled == 1
    assert stats.running == len(TaskExecutionStatus) - 3
    assert stats.total == stats.success + stats.error + stats.cancelled + stats.running
    bucket = stats.buckets[2]
    assert bucket.total == bucket.success + bucket.error + bucket.cancelled + bucket.running == stats.total


def test_aggregate_runs_accepts_naive_utc_datetimes():
    window_start, window_end = compute_hourly_window(NOW)
    aware = window_start + timedelta(hours=5, minutes=10)
    naive = aware.replace(tzinfo=None)

    stats = aggregate_runs(
        [(aware, "SUCCESS"), (naive, "ERROR")],
        window_start=window_start,
        window_end=window_end,
    )

    assert stats.buckets[5].total == 2


@pytest.mark.asyncio
async def test_runs_24h_empty(gateway_client, router_prefix):
    resp = await gateway_client.get(f"{router_prefix}/widgets/runs-24h")

    assert resp.status_code == 200, resp.json()
    payload = resp.json()
    assert payload["total"] == 0
    assert payload["success_ratio"] is None
    assert payload["bucket_minutes"] == 60
    assert len(payload["buckets"]) == 24
    assert all(bucket["total"] == 0 for bucket in payload["buckets"])


@pytest.mark.asyncio
async def test_runs_24h_window_filtering(
        gateway_client,
        router_prefix,
        test_user,
        test_user_project,
        add_task,
):
    window_start, _ = compute_hourly_window(datetime.now(UTC))
    add_task(user=test_user, project=test_user_project, queued_at=window_start + timedelta(minutes=1))
    add_task(user=test_user, project=test_user_project, queued_at=window_start - timedelta(minutes=1))

    resp = await gateway_client.get(f"{router_prefix}/widgets/runs-24h")

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["total"] == 1
    assert payload["buckets"][0]["total"] == 1


@pytest.mark.asyncio
async def test_runs_24h_status_counts_and_ratio(
        gateway_client,
        router_prefix,
        test_user,
        test_user_project,
        add_task,
):
    recent = datetime.now(UTC) - timedelta(minutes=5)
    for _ in range(3):
        add_task(user=test_user, project=test_user_project, queued_at=recent)
    add_task(user=test_user, project=test_user_project, queued_at=recent, status=TaskExecutionStatus.ERROR)
    add_task(
        user=test_user,
        project=test_user_project,
        queued_at=recent,
        status=TaskExecutionStatus.CANCELLED,
        termination_reason=TaskTerminationReason.USER_STOP.value,
    )
    add_task(user=test_user, project=test_user_project, queued_at=recent, status=TaskExecutionStatus.RUNNING)

    payload = (await gateway_client.get(f"{router_prefix}/widgets/runs-24h")).json()

    assert payload["total"] == 6
    assert payload["success"] == 3
    assert payload["error"] == 1
    assert payload["cancelled"] == 1
    assert payload["running"] == 1
    assert payload["success_ratio"] == pytest.approx(0.75)


@pytest.mark.asyncio
async def test_runs_24h_excludes_node_metadata_and_superseded(
        gateway_client,
        router_prefix,
        test_user,
        test_user_project,
        add_task,
):
    recent = datetime.now(UTC) - timedelta(minutes=5)
    add_task(user=test_user, project=test_user_project, queued_at=recent, source=TaskSource.NODE)
    add_task(
        user=test_user,
        project=test_user_project,
        queued_at=recent,
        mode=PipelineExecutionMode.METADATA_ONLY,
    )
    add_task(
        user=test_user,
        project=test_user_project,
        queued_at=recent,
        status=TaskExecutionStatus.CANCELLED,
        termination_reason=TaskTerminationReason.SUPERSEDED_BY_NEWER_EXECUTION.value,
    )

    payload = (await gateway_client.get(f"{router_prefix}/widgets/runs-24h")).json()

    assert payload["total"] == 0


@pytest.mark.asyncio
async def test_runs_24h_bucket_highlights_failed_hour(
        gateway_client,
        router_prefix,
        test_user,
        test_user_project,
        add_task,
):
    failed_at = datetime.now(UTC) - timedelta(hours=2)
    add_task(user=test_user, project=test_user_project, queued_at=failed_at, status=TaskExecutionStatus.ERROR)

    payload = (await gateway_client.get(f"{router_prefix}/widgets/runs-24h")).json()

    failed_buckets = [bucket for bucket in payload["buckets"] if bucket["error"] == 1]
    assert len(failed_buckets) == 1
    bucket_start = datetime.fromisoformat(failed_buckets[0]["start"])
    assert bucket_start <= failed_at < bucket_start + timedelta(hours=1)


@pytest.mark.asyncio
async def test_runs_24h_user_scope_isolation(
        gateway_client,
        router_prefix,
        test_user,
        test_user_project,
        test_superadmin_user,
        create_user,
        create_project,
        add_task,
        set_current_user,
):
    recent = datetime.now(UTC) - timedelta(minutes=5)
    admin_user = create_user(organization_id=test_user.organization_id, role=DVTDefaultRoles.ADMIN.value)
    colleague = create_user(organization_id=test_user.organization_id)
    colleague_project = create_project(user=colleague)
    foreign_project = create_project(user=test_superadmin_user)
    add_task(user=test_user, project=test_user_project, queued_at=recent)
    add_task(user=colleague, project=colleague_project, queued_at=recent)
    add_task(user=test_superadmin_user, project=foreign_project, queued_at=recent)

    own = (await gateway_client.get(f"{router_prefix}/widgets/runs-24h")).json()
    assert own["total"] == 1

    set_current_user(admin_user)
    org_wide = (await gateway_client.get(f"{router_prefix}/widgets/runs-24h")).json()
    assert org_wide["total"] == 2

    set_current_user(test_superadmin_user)
    global_scope = (await gateway_client.get(f"{router_prefix}/widgets/runs-24h")).json()
    assert global_scope["total"] == 3


def test_runs_24h_is_exposed_in_openapi():
    from services.gateway.main import app

    schema = app.openapi()
    assert "/widgets/runs-24h" in schema["paths"]
    properties = schema["components"]["schemas"]["RunsLast24hWidgetSchema"]["properties"]
    assert {"buckets", "success_ratio", "generated_at"} <= set(properties)
