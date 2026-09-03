from __future__ import annotations

import multiprocessing
import sys
import traceback
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from queue import Empty
from typing import Any
from uuid import uuid4

import pytest
import sqlalchemy as sa

pytestmark = pytest.mark.docker_required


DIRECT_QUERY_COUNT = 150
STRESS_ROW_COUNT = 160
STRESS_SEGMENT_COUNT = 128
CHILD_TIMEOUT_SECONDS = 180


def _fd_count() -> int | None:
    if not sys.platform.startswith("linux"):
        return None
    return sum(1 for _ in Path("/proc/self/fd").iterdir())


def _limit_open_files() -> int | None:
    if not sys.platform.startswith("linux"):
        return None

    import resource

    _, hard_limit = resource.getrlimit(resource.RLIMIT_NOFILE)
    soft_limit = (
        128
        if hard_limit == resource.RLIM_INFINITY
        else min(128, hard_limit)
    )
    resource.setrlimit(resource.RLIMIT_NOFILE, (soft_limit, hard_limit))
    return soft_limit


def _direct_pool_scenario(connection_url: str) -> dict[str, Any]:
    from clickhouse_connect.driver.httputil import all_managers

    from core.db.connect.clickhouse import (
        build_clickhouse_client_kwargs,
        close_clickhouse_pool_managers,
        create_clickhouse_client,
    )

    import config

    engine = sa.create_engine(connection_url)
    close_clickhouse_pool_managers()
    baseline_managers = set(all_managers)
    managed_managers: set[object] = set()

    try:
        client_kwargs = build_clickhouse_client_kwargs(engine)
        warm_client = create_clickhouse_client(client_kwargs)
        managed_managers.add(warm_client.http)
        try:
            assert warm_client.query("SELECT 1").first_row[0] == 1
        finally:
            warm_client.close()

        managers_after_warmup = set(all_managers)
        fd_after_warmup = _fd_count()

        for _ in range(DIRECT_QUERY_COUNT):
            client = create_clickhouse_client(client_kwargs)
            managed_managers.add(client.http)
            try:
                assert client.query("SELECT 1").first_row[0] == 1
            finally:
                client.close()

        managers_after_queries = set(all_managers)
        fd_after_queries = _fd_count()
        pool_maxsize = int(config.CLICKHOUSE.HTTP_POOL_MAXSIZE)

        assert len(managed_managers) == 1
        assert len(managers_after_warmup - baseline_managers) == 1
        assert managers_after_queries == managers_after_warmup
        if fd_after_warmup is not None and fd_after_queries is not None:
            assert fd_after_queries - fd_after_warmup <= pool_maxsize + 8

        manager = next(iter(managed_managers))
        close_clickhouse_pool_managers()
        assert manager not in all_managers

        return {
            "managed_manager_count": len(managed_managers),
            "manager_growth_after_warmup": len(
                managers_after_queries - managers_after_warmup
            ),
            "fd_delta": (
                None
                if fd_after_warmup is None or fd_after_queries is None
                else fd_after_queries - fd_after_warmup
            ),
            "pool_maxsize": pool_maxsize,
        }
    finally:
        close_clickhouse_pool_managers()
        engine.dispose()


def _dask_read_v3_scenario(connection_url: str, table_name: str) -> dict[str, Any]:
    from clickhouse_connect.driver.httputil import all_managers

    from core.db.connect.clickhouse import (
        build_clickhouse_client_kwargs,
        close_clickhouse_pool_managers,
        create_clickhouse_client,
    )
    from core.db.read_v3.dask import frame_from_executor
    from core.db.read_v3.resolver import resolve_executor, resolve_planner

    import config

    nofile_soft_limit = _limit_open_files()
    engine = sa.create_engine(connection_url)
    close_clickhouse_pool_managers()
    client_kwargs = build_clickhouse_client_kwargs(engine)
    managed_manager: object | None = None

    try:
        setup_client = create_clickhouse_client(client_kwargs)
        managed_manager = setup_client.http
        try:
            setup_client.command(f"DROP TABLE IF EXISTS {table_name}")
            setup_client.command(
                f"""
                CREATE TABLE {table_name} (
                    id UInt64,
                    payload String
                )
                ENGINE = MergeTree
                ORDER BY id
                """
            )
            setup_client.insert(
                table_name,
                [[row_id, f"value-{row_id}"] for row_id in range(STRESS_ROW_COUNT)],
                column_names=["id", "payload"],
            )
        finally:
            setup_client.close()

        planner = resolve_planner(mode="table")
        plan = planner.build_plan(
            engine=engine,
            table_name=table_name,
            columns=["id", "payload"],
            partition_col="id",
            npartitions=STRESS_SEGMENT_COUNT,
            partition_grouping={"mode": "hash", "buckets": STRESS_SEGMENT_COUNT},
            max_rows_per_partition=64,
            min_rows_per_partition=1,
            target_partition_mem_mb=1,
            partitioning_overhead_coef=1.0,
            max_partitions=STRESS_SEGMENT_COUNT,
        )
        assert plan.segment_count == STRESS_SEGMENT_COUNT

        executor = resolve_executor(engine)
        ddf = frame_from_executor(executor, plan)
        managers_before_compute = set(all_managers)
        fd_before_compute = _fd_count()

        result = ddf.compute(scheduler="threads", num_workers=4)

        managers_after_compute = set(all_managers)
        fd_after_compute = _fd_count()
        check_client = create_clickhouse_client(client_kwargs)
        try:
            assert check_client.http is managed_manager
        finally:
            check_client.close()

        ids = sorted(int(value) for value in result["id"].tolist())
        pool_maxsize = int(config.CLICKHOUSE.HTTP_POOL_MAXSIZE)

        assert ids == list(range(STRESS_ROW_COUNT))
        assert not result["id"].duplicated().any()
        assert managers_after_compute == managers_before_compute
        if fd_before_compute is not None and fd_after_compute is not None:
            assert fd_after_compute - fd_before_compute <= pool_maxsize + 8

        return {
            "rows": len(result),
            "segments": plan.segment_count,
            "managed_manager_count": 1,
            "manager_growth_during_compute": len(
                managers_after_compute - managers_before_compute
            ),
            "fd_delta": (
                None
                if fd_before_compute is None or fd_after_compute is None
                else fd_after_compute - fd_before_compute
            ),
            "nofile_soft_limit": nofile_soft_limit,
            "pool_maxsize": pool_maxsize,
        }
    finally:
        close_clickhouse_pool_managers()
        with suppress(Exception):
            cleanup_client = create_clickhouse_client(client_kwargs)
            try:
                cleanup_client.command(f"DROP TABLE IF EXISTS {table_name}")
            finally:
                cleanup_client.close()
        close_clickhouse_pool_managers()
        engine.dispose()


def _child_entry(
    scenario: Callable[..., dict[str, Any]],
    result_queue,
    *args: str,
) -> None:
    try:
        result_queue.put({"ok": True, "result": scenario(*args)})
    except BaseException:
        result_queue.put({"ok": False, "traceback": traceback.format_exc()})


def _run_spawned(
    scenario: Callable[..., dict[str, Any]],
    *args: str,
) -> dict[str, Any]:
    project_root = str(Path(__file__).resolve().parents[5])
    if not sys.path or sys.path[0] != project_root:
        sys.path.insert(0, project_root)

    context = multiprocessing.get_context("spawn")
    result_queue = context.Queue()
    process = context.Process(
        target=_child_entry,
        args=(scenario, result_queue, *args),
    )
    process.start()
    process.join(CHILD_TIMEOUT_SECONDS)

    if process.is_alive():
        process.terminate()
        process.join(10)
        pytest.fail(f"Spawned ClickHouse scenario timed out after {CHILD_TIMEOUT_SECONDS}s")

    try:
        payload = result_queue.get(timeout=10)
    except Empty:
        pytest.fail(
            "Spawned ClickHouse scenario returned no diagnostics; "
            f"child exit code={process.exitcode}"
        )
    finally:
        result_queue.close()
        result_queue.join_thread()

    assert payload["ok"], payload.get("traceback", "Spawned ClickHouse scenario failed")
    assert process.exitcode == 0
    return payload["result"]


def _connection_url(engine: sa.Engine) -> str:
    return engine.url.render_as_string(hide_password=False)


def test_clickhouse_pool_manager_stays_bounded_after_150_queries(
    clickhouse_http_test_engine: sa.Engine,
) -> None:
    result = _run_spawned(
        _direct_pool_scenario,
        _connection_url(clickhouse_http_test_engine),
    )

    assert result["managed_manager_count"] == 1
    assert result["manager_growth_after_warmup"] == 0
    if result["fd_delta"] is not None:
        assert result["fd_delta"] <= result["pool_maxsize"] + 8


def test_clickhouse_read_v3_dask_stays_bounded_under_low_nofile(
    clickhouse_http_test_engine: sa.Engine,
) -> None:
    result = _run_spawned(
        _dask_read_v3_scenario,
        _connection_url(clickhouse_http_test_engine),
        f"read_v3_pool_stress_{uuid4().hex[:12]}",
    )

    assert result["rows"] == STRESS_ROW_COUNT
    assert result["segments"] == STRESS_SEGMENT_COUNT
    assert result["managed_manager_count"] == 1
    assert result["manager_growth_during_compute"] == 0
    if sys.platform.startswith("linux"):
        assert result["nofile_soft_limit"] == 128
        assert result["fd_delta"] <= result["pool_maxsize"] + 8
