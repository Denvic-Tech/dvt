from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import orjson
import pytest
import redis
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from celery import Celery
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import Session, SQLModel, select

from src.enums import DVTDefaultRoles, ExtensionDepsStatus
from src.models import OrganizationRecord
from src.models.extension import ExtensionRecord
from src.modules.project.infra.db_models import ProjectRecord
from src.modules.task_execution.domain.types import TaskExecutionStatus
from src.modules.task_execution.flow.use_cases import FinalizeReconciledExecutionUseCase
from src.modules.task_execution.infra.db_models import TaskRecord
from src.modules.task_execution.infra.repositories import SQLTaskExecutionRepository
from src.modules.user.infra.db_models import UserRecord
from src.node_dsl.core.input_values import NodeInputConstantValue, NodeInputLinkValue
from src.pipeline.execution_mode import PipelineExecutionMode
from src.schemas.internal import (
    NodeData,
    ProjectSettings,
    ProjectVariables,
    TaskInternal,
)

pytestmark = [pytest.mark.docker_required]


def _stamp_database_at_alembic_head(*, engine, repo_root: Path) -> None:
    alembic_config = Config(str(repo_root / "alembic.ini"))
    script_directory = ScriptDirectory.from_config(alembic_config)

    with engine.begin() as connection:
        MigrationContext.configure(connection).stamp(script_directory, "head")


def _build_task_payload(*, project_id: str, task_id: str, user_id: str) -> dict:
    pipeline = {
        "create_variable": NodeData(
            name="CreateVariable",
            inputs={
                "name": NodeInputConstantValue(value="celery_test_var"),
                "type": NodeInputConstantValue(value="STRING"),
                "value": NodeInputConstantValue(value="hello from celery"),
            },
        ),
    }

    task = TaskInternal(
        project_id=project_id,
        task_id=task_id,
        user_id=user_id,
        pipeline=pipeline,
        target_nodes=["create_variable"],
        mode=PipelineExecutionMode.FULL,
        send_ws_messages=False,
        project_settings=ProjectSettings(
            store_enabled=False,
            ttl_time=0,
            workers_count=1,
        ),
        project_variables=ProjectVariables(variables={}),
    )
    return task.model_dump(mode="json")


def _build_sleep_task_payload(
    *,
    project_id: str,
    task_id: str,
    user_id: str,
    sleep_seconds: int,
    two_nodes: bool = False,
    send_ws_messages: bool = False,
) -> dict:
    pipeline = {
        "sleep_a": NodeData(
            name="TimeSleepNode",
            inputs={
                "value_in": NodeInputConstantValue(value="first"),
                "sleep_time_sec": NodeInputConstantValue(value=sleep_seconds),
            },
        ),
    }
    target_nodes = ["sleep_a"]
    if two_nodes:
        pipeline["sleep_b"] = NodeData(
            name="TimeSleepNode",
            inputs={
                "value_in": NodeInputLinkValue(node_id="sleep_a", output_name="value_out"),
                "sleep_time_sec": NodeInputConstantValue(value=sleep_seconds),
            },
        )
        target_nodes = ["sleep_b"]

    task = TaskInternal(
        project_id=project_id,
        task_id=task_id,
        user_id=user_id,
        pipeline=pipeline,
        target_nodes=target_nodes,
        mode=PipelineExecutionMode.FULL,
        send_ws_messages=send_ws_messages,
        project_settings=ProjectSettings(store_enabled=False, ttl_time=0, workers_count=1),
        project_variables=ProjectVariables(variables={}),
    )
    return task.model_dump(mode="json")


def _write_extension_marker_fixture(
    *,
    extensions_root: Path,
    extension_name: str,
    version: str,
    marker_value: str,
) -> Path:
    extension_root = extensions_root / extension_name
    package_root = extension_root / "test_runtime_extension"
    nodes_root = package_root / "nodes"
    nodes_root.mkdir(parents=True, exist_ok=True)
    (package_root / "__init__.py").write_text("", encoding="utf-8")
    (nodes_root / "__init__.py").write_text(
        "from .marker import ExtensionMarkerNode\n\n__all__ = ['ExtensionMarkerNode']\n",
        encoding="utf-8",
    )
    (nodes_root / "marker.py").write_text(
        "from pathlib import Path\n"
        "from src.node_dsl import TestingBaseNode, InputField, OutputField\n"
        "from src.node_dsl.node_typing import IO\n\n"
        "class ExtensionMarkerNode(TestingBaseNode):\n"
        "    TITLE = 'Extension Marker'\n"
        "    CATEGORY = 'Testing'\n"
        "    marker_path: IO.STRING = InputField()\n"
        "    value_out: IO.STRING = OutputField()\n\n"
        "    def process(self):\n"
        f"        Path(self.marker_path).write_text({marker_value!r}, encoding='utf-8')\n"
        f"        self.value_out = {marker_value!r}\n",
        encoding="utf-8",
    )
    (extension_root / "pyproject.toml").write_text(
        "[project]\n"
        "name = 'dvt-test-runtime-extension'\n"
        f"version = '{version}'\n"
        "description = 'Task Worker persistent child integration fixture'\n"
        "dependencies = []\n\n"
        "[tool.dvt_extension]\n"
        f"name = '{extension_name}'\n"
        "display_name = 'Task Worker Runtime Fixture'\n"
        "dvt_version = '*'\n"
        "state_schema = {}\n"
        "backend = { nodes_dir = 'test_runtime_extension/nodes' }\n\n"
        "[[tool.dvt_extension.nodes]]\n"
        "name = 'ExtensionMarkerNode'\n"
        "display_name = 'Extension Marker'\n"
        "description = 'Writes a marker proving which runtime generation executed.'\n",
        encoding="utf-8",
    )
    return extension_root


def _build_extension_marker_payload(
    *,
    project_id: str,
    task_id: str,
    user_id: str,
    extension_name: str,
    marker_path: Path,
) -> dict:
    task = TaskInternal(
        project_id=project_id,
        task_id=task_id,
        user_id=user_id,
        pipeline={
            "extension_marker": NodeData(
                name="ExtensionMarkerNode",
                inputs={
                    "marker_path": NodeInputConstantValue(value=str(marker_path)),
                },
            ),
        },
        target_nodes=["extension_marker"],
        mode=PipelineExecutionMode.FULL,
        send_ws_messages=False,
        extension_names=[extension_name],
        project_settings=ProjectSettings(store_enabled=False, ttl_time=0, workers_count=1),
        project_variables=ProjectVariables(variables={}),
    )
    return task.model_dump(mode="json")


def _wait_task_status(
    *,
    engine,
    task_id: str,
    timeout_sec: float = 90.0,
    interval_sec: float = 0.5,
) -> TaskExecutionStatus | None:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        with Session(engine) as session:
            task = session.exec(select(TaskRecord).where(TaskRecord.task_id == task_id)).first()
            if task is not None and task.status in (
                TaskExecutionStatus.SUCCESS,
                TaskExecutionStatus.ERROR,
                TaskExecutionStatus.CANCELLED,
            ):
                return task.status
        time.sleep(interval_sec)
    return None


def _wait_task_in_status(
    *,
    engine,
    task_id: str,
    expected: TaskExecutionStatus,
    timeout_sec: float = 30.0,
) -> TaskRecord:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        with Session(engine) as session:
            task = session.exec(select(TaskRecord).where(TaskRecord.task_id == task_id)).first()
            if task is not None and task.status == expected:
                return task
            if task is not None and task.status in (
                TaskExecutionStatus.SUCCESS,
                TaskExecutionStatus.ERROR,
                TaskExecutionStatus.CANCELLED,
            ):
                raise AssertionError(
                    f"Task {task_id} reached {task.status} before expected {expected}"
                )
        time.sleep(0.05)
    raise AssertionError(f"Task {task_id} did not reach {expected} within {timeout_sec}s")


def _read_task_telemetry_pids(redis_client: redis.Redis, task_id: str) -> list[int]:
    pids: list[int] = []
    for _entry_id, fields in redis_client.xrange("orchestrator.events", min="-", max="+"):
        raw_payload = fields.get(b"payload") or fields.get("payload")
        if raw_payload is None:
            continue
        payload = orjson.loads(raw_payload)
        if payload.get("task_id") != task_id:
            continue
        event = payload.get("event") or {}
        pid = event.get("pid")
        if isinstance(pid, int):
            pids.append(pid)
    return pids


def _read_started_node_ids(redis_client: redis.Redis, task_id: str) -> set[str]:
    node_ids: set[str] = set()
    for _entry_id, fields in redis_client.xrange("orchestrator.events", min="-", max="+"):
        raw_payload = fields.get(b"payload") or fields.get("payload")
        if raw_payload is None:
            continue
        payload = orjson.loads(raw_payload)
        if payload.get("task_id") != task_id:
            continue
        event = payload.get("event") or {}
        node_id = event.get("node_id")
        status = event.get("status")
        if isinstance(node_id, str) and status in {"RUNNING", "running"}:
            node_ids.add(node_id)
    return node_ids


def _insert_queued_task(
    *,
    engine,
    task_id: str,
    user_id: str,
    organization_id: str,
    project_id: str,
) -> None:
    with Session(engine) as session:
        session.add(
            TaskRecord(
                task_id=task_id,
                mode=PipelineExecutionMode.FULL,
                force_exec=False,
                status=TaskExecutionStatus.QUEUED,
                assigned_worker_id=None,
                user_id=user_id,
                organization_id=organization_id,
                project_id=project_id,
            )
        )
        session.commit()


def _read_worker_logs(worker_log_path: str | None) -> str:
    if not worker_log_path or not os.path.exists(worker_log_path):
        return ""

    with open(worker_log_path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


def _wait_workers_ready(
    *,
    celery_client: Celery,
    worker_procs: list[subprocess.Popen],
    worker_log_paths: list[str | None],
    expected_count: int,
    timeout_sec: float = 300.0,
    ping_timeout_sec: float = 1.0,
) -> set[str]:
    deadline = time.monotonic() + timeout_sec
    last_ping_error: Exception | None = None
    seen_worker_ids: set[str] = set()

    while time.monotonic() < deadline:
        for index, worker_proc in enumerate(worker_procs):
            exit_code = worker_proc.poll()
            if exit_code is not None:
                raise AssertionError(
                    f"Task worker #{index + 1} exited with code {exit_code} before all workers "
                    f"became ready. Worker logs:\n{_read_worker_logs(worker_log_paths[index])}"
                )

        try:
            responses = celery_client.control.ping(timeout=ping_timeout_sec)
            if responses:
                seen_worker_ids.update(
                    worker_name.removeprefix("celery@")
                    for response in responses
                    for worker_name in response
                )
                if len(seen_worker_ids) >= expected_count:
                    return seen_worker_ids
        except Exception as exc:
            last_ping_error = exc

    error_suffix = f" Last ping error: {last_ping_error}" if last_ping_error else ""
    logs = "\n\n".join(
        f"worker #{index + 1}:\n{_read_worker_logs(path)}"
        for index, path in enumerate(worker_log_paths)
    )
    raise AssertionError(
        f"Expected {expected_count} Task Workers to become ready within {timeout_sec:.0f} seconds."
        f"{error_suffix} Worker logs:\n{logs}"
    )


def test_two_task_workers_persist_actual_claiming_worker_id(postgres_container, redis_container):
    repo_root = Path(__file__).resolve().parents[4]
    base_url = make_url(postgres_container.get_connection_url())
    admin_db_name = base_url.database
    assert admin_db_name, "Postgres test container must provide database name in URL"

    test_db_name = f"tw_celery_{uuid4().hex[:8]}"

    admin_url = base_url.set(database=admin_db_name)
    admin_engine = create_engine(admin_url.render_as_string(hide_password=False), isolation_level="AUTOCOMMIT")

    with admin_engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{test_db_name}"'))

    test_url = base_url.set(database=test_db_name)
    test_engine = create_engine(test_url.render_as_string(hide_password=False))

    worker_procs: list[subprocess.Popen] = []
    worker_log_paths: list[str] = []
    worker_log_files = []

    try:
        SQLModel.metadata.create_all(test_engine)
        _stamp_database_at_alembic_head(engine=test_engine, repo_root=repo_root)

        user_id = f"user-{uuid4().hex[:8]}"
        organization_id = f"org-{uuid4().hex[:8]}"
        project_id = f"project-{uuid4().hex[:8]}"
        task_id = f"task-{uuid4().hex[:8]}"

        with Session(test_engine) as session:
            organization = OrganizationRecord(
                id=organization_id,
                name="integration-org",
            )
            session.add(organization)
            session.flush()

            user = UserRecord(
                id=user_id,
                email=f"{user_id}@example.com",
                hashed_password="not_used_in_test",
                auth_provider="email",
                is_verified=True,
                is_active=True,
                role=DVTDefaultRoles.USER.value,
                organization_id=organization_id,
            )
            session.add(user)
            session.flush()

            project = ProjectRecord(
                id=project_id,
                name="integration_project",
                user_id=user_id,
                organization_id=organization_id,
                store_enabled=False,
                ttl_time=0,
                workers_count=1,
                variables={},
            )
            session.add(project)
            session.flush()

            task_entry = TaskRecord(
                task_id=task_id,
                mode=PipelineExecutionMode.FULL,
                force_exec=False,
                status=TaskExecutionStatus.QUEUED,
                assigned_worker_id=None,
                user_id=user_id,
                organization_id=organization_id,
                project_id=project_id,
            )
            session.add(task_entry)
            session.flush()

            session.commit()

        broker_host = redis_container.get_container_host_ip()
        broker_port = redis_container.get_exposed_port(redis_container.port)
        broker_url = f"redis://{broker_host}:{broker_port}/0"

        env = os.environ.copy()
        env.update(
            {
                "SERVICE_NAME": "task-worker",
                "LOG_TO_WS": "false",
                "LOG_TO_DB": "false",
                "INTERCEPT_STANDARD_LOGGING": "false",
                "VALKEY_HOST": broker_host,
                "VALKEY_PORT": str(broker_port),
                "VALKEY_PASSWORD": "",
                "CELERY_BROKER_URL": broker_url,
                "CELERY_RESULT_BACKEND": broker_url,
                "CELERY_WORKER_POOL": "prefork",
                "CELERY_WORKER_CONCURRENCY": "1",
                "POSTGRES_HOST": test_url.host or "127.0.0.1",
                "POSTGRES_PORT": str(test_url.port or 5432),
                "POSTGRES_DB": test_db_name,
                "POSTGRES_USER": test_url.username or "postgres",
                "POSTGRES_PASSWORD": test_url.password or "",
            }
        )

        for _ in range(2):
            worker_log_file = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False)
            worker_log_files.append(worker_log_file)
            worker_log_paths.append(worker_log_file.name)
            worker_procs.append(
                subprocess.Popen(
                    [sys.executable, str(repo_root / "scripts" / "services" / "run_task_worker.py")],
                    cwd=str(repo_root),
                    env=env,
                    stdout=worker_log_file,
                    stderr=subprocess.STDOUT,
                )
            )

        celery_client = Celery("integration-orchestrator", broker=broker_url, backend=broker_url)
        live_worker_ids = _wait_workers_ready(
            celery_client=celery_client,
            worker_procs=worker_procs,
            worker_log_paths=worker_log_paths,
            expected_count=2,
        )

        payload = _build_task_payload(project_id=project_id, task_id=task_id, user_id=user_id)
        celery_client.send_task(
            "task_worker.handle_task",
            args=[payload],
            queue="tasks.worker",
            task_id=task_id,
        )

        status = _wait_task_status(engine=test_engine, task_id=task_id, timeout_sec=120.0)
        if status != TaskExecutionStatus.SUCCESS:
            logs = "\n\n".join(_read_worker_logs(path) for path in worker_log_paths)
            raise AssertionError(
                f"Expected task status SUCCESS, got {status}. Worker logs:\n{logs}"
            )

        with Session(test_engine) as session:
            completed_task = session.exec(
                select(TaskRecord).where(TaskRecord.task_id == task_id)
            ).one()
        assert completed_task.assigned_worker_id in live_worker_ids
        assert completed_task.assigned_worker_id is not None

    finally:
        for worker_log_file in worker_log_files:
            worker_log_file.flush()
            worker_log_file.close()

        for worker_proc in worker_procs:
            worker_proc.terminate()
            try:
                worker_proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                worker_proc.kill()
                worker_proc.wait(timeout=10)

        test_engine.dispose()

        for worker_log_path in worker_log_paths:
            if os.path.exists(worker_log_path):
                try:
                    os.remove(worker_log_path)
                except OSError:
                    pass

        with admin_engine.connect() as conn:
            conn.execute(
                text(
                    """
                    SELECT pg_terminate_backend(pid)
                    FROM pg_stat_activity
                    WHERE datname = :db_name
                      AND pid <> pg_backend_pid()
                    """
                ),
                {"db_name": test_db_name},
            )
            conn.execute(text(f'DROP DATABASE IF EXISTS "{test_db_name}"'))

        admin_engine.dispose()


def test_persistent_prefork_child_stop_kill_and_single_slot_lifecycle(
    postgres_container,
    redis_container,
):
    """Exercise real Celery processes rather than configuration-only assertions.

    RSS is deliberately not asserted: allocator/Dask process RSS is not monotonic or
    deterministic across platforms. PID reuse plus no task-scoped .partd leftovers
    provide stable evidence that a persistent execution child is reused and cleaned.
    """
    repo_root = Path(__file__).resolve().parents[4]
    base_url = make_url(postgres_container.get_connection_url())
    admin_db_name = base_url.database
    assert admin_db_name
    test_db_name = f"tw_lifecycle_{uuid4().hex[:8]}"
    admin_url = base_url.set(database=admin_db_name)
    admin_engine = create_engine(
        admin_url.render_as_string(hide_password=False), isolation_level="AUTOCOMMIT"
    )
    with admin_engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{test_db_name}"'))

    test_url = base_url.set(database=test_db_name)
    test_engine = create_engine(test_url.render_as_string(hide_password=False))
    worker_proc: subprocess.Popen | None = None
    worker_log_file = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False)
    worker_log_path = worker_log_file.name
    worker_tmp = tempfile.mkdtemp(prefix="dvt-celery-lifecycle-")
    extensions_root = Path(worker_tmp) / "extensions"
    extension_name = "task-worker-runtime-fixture"
    extension_root = _write_extension_marker_fixture(
        extensions_root=extensions_root,
        extension_name=extension_name,
        version="1.0.0",
        marker_value="runtime-v1",
    )
    async_engine = None

    try:
        SQLModel.metadata.create_all(test_engine)
        _stamp_database_at_alembic_head(engine=test_engine, repo_root=repo_root)

        user_id = f"user-{uuid4().hex[:8]}"
        organization_id = f"org-{uuid4().hex[:8]}"
        project_id = f"project-{uuid4().hex[:8]}"
        with Session(test_engine) as session:
            session.add(OrganizationRecord(id=organization_id, name="lifecycle-org"))
            session.flush()
            session.add(
                UserRecord(
                    id=user_id,
                    email=f"{user_id}@example.com",
                    hashed_password="not_used_in_test",
                    auth_provider="email",
                    is_verified=True,
                    is_active=True,
                    role=DVTDefaultRoles.USER.value,
                    organization_id=organization_id,
                )
            )
            session.flush()
            session.add(
                ProjectRecord(
                    id=project_id,
                    name="lifecycle_project",
                    user_id=user_id,
                    organization_id=organization_id,
                    store_enabled=False,
                    ttl_time=0,
                    workers_count=1,
                    variables={},
                )
            )
            session.add(
                ExtensionRecord(
                    name=extension_name,
                    display_name="Task Worker Runtime Fixture",
                    is_installed=True,
                    is_enabled=True,
                    deps_status=ExtensionDepsStatus.READY,
                    current_version="1.0.0",
                    last_version="1.0.0",
                    install_path=str(extension_root),
                    installed_at=datetime.now(tz=UTC),
                )
            )
            session.commit()

        broker_host = redis_container.get_container_host_ip()
        broker_port = redis_container.get_exposed_port(redis_container.port)
        broker_url = f"redis://{broker_host}:{broker_port}/0"
        redis_client = redis.Redis(host=broker_host, port=int(broker_port), decode_responses=False)
        redis_client.delete("orchestrator.events")

        env = os.environ.copy()
        env.update(
            {
                "SERVICE_NAME": "task-worker",
                # A task below emits WS-eligible logs before child termination. The
                # child may fail to reach a Gateway in this isolated test, but the
                # critical invariant is that the MainProcess never owns that client.
                "LOG_TO_WS": "true",
                "LOG_TO_DB": "false",
                "INTERCEPT_STANDARD_LOGGING": "false",
                "DEBUG": "true",
                "TASK_EXECUTION_TELEMETRY_INTERVAL_SEC": "0.1",
                "TASK_CANCELLATION_POLL_INTERVAL_SEC": "0.1",
                "VALKEY_HOST": broker_host,
                "VALKEY_PORT": str(broker_port),
                "VALKEY_PASSWORD": "",
                "CELERY_BROKER_URL": broker_url,
                "CELERY_RESULT_BACKEND": broker_url,
                "CELERY_WORKER_POOL": "prefork",
                "CELERY_WORKER_CONCURRENCY": "1",
                "TASK_WORKER_MAX_CONCURRENT": "1",
                "EXTENSIONS_ENABLED": "true",
                "EXTENSIONS_AUTOLOAD": "true",
                "EXTENSIONS_DATA_DIR": str(extensions_root),
                "POSTGRES_HOST": test_url.host or "127.0.0.1",
                "POSTGRES_PORT": str(test_url.port or 5432),
                "POSTGRES_DB": test_db_name,
                "POSTGRES_USER": test_url.username or "postgres",
                "POSTGRES_PASSWORD": test_url.password or "",
                "TMPDIR": worker_tmp,
                "TEMP": worker_tmp,
                "TMP": worker_tmp,
            }
        )
        worker_proc = subprocess.Popen(
            [sys.executable, str(repo_root / "scripts" / "services" / "run_task_worker.py")],
            cwd=str(repo_root),
            env=env,
            stdout=worker_log_file,
            stderr=subprocess.STDOUT,
        )
        celery_client = Celery("integration-lifecycle", broker=broker_url, backend=broker_url)
        _wait_workers_ready(
            celery_client=celery_client,
            worker_procs=[worker_proc],
            worker_log_paths=[worker_log_path],
            expected_count=1,
        )

        def _dispatch_sleep(
            task_id: str,
            *,
            seconds: int,
            two_nodes: bool = False,
            send_ws_messages: bool = False,
        ) -> None:
            _insert_queued_task(
                engine=test_engine,
                task_id=task_id,
                user_id=user_id,
                organization_id=organization_id,
                project_id=project_id,
            )
            celery_client.send_task(
                "task_worker.handle_task",
                args=[
                    _build_sleep_task_payload(
                        project_id=project_id,
                        task_id=task_id,
                        user_id=user_id,
                        sleep_seconds=seconds,
                        two_nodes=two_nodes,
                        send_ws_messages=send_ws_messages,
                    )
                ],
                queue="tasks.worker",
                task_id=task_id,
            )

        def _dispatch_extension_marker(task_id: str, marker_path: Path) -> None:
            _insert_queued_task(
                engine=test_engine,
                task_id=task_id,
                user_id=user_id,
                organization_id=organization_id,
                project_id=project_id,
            )
            celery_client.send_task(
                "task_worker.handle_task",
                args=[
                    _build_extension_marker_payload(
                        project_id=project_id,
                        task_id=task_id,
                        user_id=user_id,
                        extension_name=extension_name,
                        marker_path=marker_path,
                    )
                ],
                queue="tasks.worker",
                task_id=task_id,
            )

        def _wait_pid(task_id: str, timeout_sec: float = 10.0) -> int:
            deadline = time.time() + timeout_sec
            while time.time() < deadline:
                pids = _read_task_telemetry_pids(redis_client, task_id)
                if pids:
                    return pids[-1]
                time.sleep(0.05)
            raise AssertionError(f"No telemetry PID received for {task_id}")

        # Persistent child: several real PipelineProcessor/Dask tasks reuse one PID.
        persistent_pids: list[int] = []
        for suffix in ("a", "b", "c"):
            task_id = f"persistent-{suffix}-{uuid4().hex[:6]}"
            _dispatch_sleep(task_id, seconds=1)
            assert _wait_task_status(engine=test_engine, task_id=task_id) == TaskExecutionStatus.SUCCESS
            persistent_pids.append(_wait_pid(task_id))
        assert len(set(persistent_pids)) == 1
        assert not list(Path(worker_tmp).rglob("*.partd"))

        # Real extension node execution uses the same persistent child/runtime.
        extension_pids: list[int] = []
        for suffix in ("a", "b"):
            task_id = f"extension-v1-{suffix}-{uuid4().hex[:6]}"
            marker_path = Path(worker_tmp) / f"{task_id}.txt"
            _dispatch_extension_marker(task_id, marker_path)
            assert _wait_task_status(engine=test_engine, task_id=task_id) == TaskExecutionStatus.SUCCESS
            extension_pids.append(_wait_pid(task_id))
            assert marker_path.read_text(encoding="utf-8") == "runtime-v1"
        assert len(set(extension_pids)) == 1
        assert extension_pids[0] == persistent_pids[-1]

        # Simulate a completed extension update: shared files and PostgreSQL
        # generation change, but no Celery child recycling.
        time.sleep(1.1)
        _write_extension_marker_fixture(
            extensions_root=extensions_root,
            extension_name=extension_name,
            version="2.0.0",
            marker_value="runtime-v2-updated",
        )
        with Session(test_engine) as session:
            extension_row = session.exec(
                select(ExtensionRecord).where(ExtensionRecord.name == extension_name)
            ).one()
            extension_row.current_version = "2.0.0"
            extension_row.last_version = "2.0.0"
            extension_row.installed_at = datetime.now(tz=UTC)
            session.add(extension_row)
            session.commit()

        updated_task_id = f"extension-v2-{uuid4().hex[:6]}"
        updated_marker_path = Path(worker_tmp) / f"{updated_task_id}.txt"
        _dispatch_extension_marker(updated_task_id, updated_marker_path)
        assert _wait_task_status(engine=test_engine, task_id=updated_task_id) == TaskExecutionStatus.SUCCESS
        assert updated_marker_path.read_text(encoding="utf-8") == "runtime-v2-updated"
        assert _wait_pid(updated_task_id) == extension_pids[-1]

        # One container == one pipeline slot: second long task remains QUEUED.
        first = f"single-slot-a-{uuid4().hex[:6]}"
        second = f"single-slot-b-{uuid4().hex[:6]}"
        _dispatch_sleep(first, seconds=3)
        _dispatch_sleep(second, seconds=3)
        _wait_task_in_status(engine=test_engine, task_id=first, expected=TaskExecutionStatus.RUNNING)
        time.sleep(0.4)
        with Session(test_engine) as session:
            second_row = session.exec(
                select(TaskRecord).where(TaskRecord.task_id == second)
            ).one()
        assert second_row.status == TaskExecutionStatus.QUEUED
        assert _wait_task_status(engine=test_engine, task_id=first) == TaskExecutionStatus.SUCCESS
        assert _wait_task_status(engine=test_engine, task_id=second) == TaskExecutionStatus.SUCCESS

        # Cooperative STOP: current node completes, next node must never start.
        stopped_id = f"cooperative-stop-{uuid4().hex[:6]}"
        stop_log_offset = os.path.getsize(worker_log_path)
        _dispatch_sleep(stopped_id, seconds=2, two_nodes=True)
        _wait_task_in_status(engine=test_engine, task_id=stopped_id, expected=TaskExecutionStatus.RUNNING)
        time.sleep(0.3)
        with Session(test_engine) as session:
            row = session.exec(select(TaskRecord).where(TaskRecord.task_id == stopped_id)).one()
            row.status = TaskExecutionStatus.CANCEL_REQUESTED
            row.termination_reason = "USER_STOP"
            session.add(row)
            session.commit()
        assert _wait_task_status(engine=test_engine, task_id=stopped_id) == TaskExecutionStatus.CANCELLED
        with Session(test_engine) as session:
            row = session.exec(select(TaskRecord).where(TaskRecord.task_id == stopped_id)).one()
        assert row.termination_reason == "USER_STOP"
        time.sleep(0.1)
        with open(worker_log_path, "r", encoding="utf-8", errors="replace") as log_file:
            log_file.seek(stop_log_offset)
            stop_task_logs = log_file.read()
        assert stop_task_logs.count("sleep time: 2") == 1

        # STOP escalation: after the production 10s grace window a blocking node
        # is hard-terminated, but the authoritative semantic reason remains USER_STOP.
        escalated_id = f"stop-escalation-{uuid4().hex[:6]}"
        _dispatch_sleep(escalated_id, seconds=20)
        _wait_task_in_status(engine=test_engine, task_id=escalated_id, expected=TaskExecutionStatus.RUNNING)
        escalated_pid = _wait_pid(escalated_id)
        with Session(test_engine) as session:
            row = session.exec(select(TaskRecord).where(TaskRecord.task_id == escalated_id)).one()
            row.status = TaskExecutionStatus.CANCEL_REQUESTED
            row.termination_reason = "USER_STOP"
            session.add(row)
            session.commit()
        time.sleep(10.1)
        celery_client.control.revoke(escalated_id, terminate=True, destination=None)
        time.sleep(1.0)
        assert worker_proc.poll() is None, _read_worker_logs(worker_log_path)

        async_url = test_url.set(drivername="postgresql+psycopg")
        async_engine = create_async_engine(async_url.render_as_string(hide_password=False))
        factory = async_sessionmaker(async_engine, expire_on_commit=False)
        reconciled = asyncio.run(
            FinalizeReconciledExecutionUseCase(SQLTaskExecutionRepository(factory)).execute(
                task_id=escalated_id,
                termination_reason="USER_STOP",
            )
        )
        assert reconciled is not None
        assert reconciled.status == TaskExecutionStatus.CANCELLED.value
        assert reconciled.termination_reason == "USER_STOP"

        after_escalation = f"after-escalation-{uuid4().hex[:6]}"
        _dispatch_sleep(after_escalation, seconds=1)
        assert _wait_task_status(engine=test_engine, task_id=after_escalation) == TaskExecutionStatus.SUCCESS
        assert _wait_pid(after_escalation) != escalated_pid

        # Unexpected execution-child death is reported by Celery's MainProcess as
        # WorkerLostError. PostgreSQL must become ERROR/WORKER_LOST without any
        # implicit pipeline retry, while Celery replaces only the child process.
        killed_id = f"unexpected-child-loss-{uuid4().hex[:6]}"
        _dispatch_sleep(killed_id, seconds=20, send_ws_messages=True)
        _wait_task_in_status(engine=test_engine, task_id=killed_id, expected=TaskExecutionStatus.RUNNING)
        killed_pid = _wait_pid(killed_id)
        os.kill(killed_pid, getattr(signal, "SIGKILL", signal.SIGTERM))

        assert _wait_task_status(engine=test_engine, task_id=killed_id, timeout_sec=30.0) == TaskExecutionStatus.ERROR
        assert worker_proc.poll() is None, _read_worker_logs(worker_log_path)
        with Session(test_engine) as session:
            killed_row = session.exec(
                select(TaskRecord).where(TaskRecord.task_id == killed_id)
            ).one()
        assert killed_row.termination_reason == "WORKER_LOST"
        assert set(_read_task_telemetry_pids(redis_client, killed_id)) == {killed_pid}

        after_kill = f"after-kill-{uuid4().hex[:6]}"
        _dispatch_sleep(after_kill, seconds=1)
        assert _wait_task_status(engine=test_engine, task_id=after_kill) == TaskExecutionStatus.SUCCESS
        replacement_pid = _wait_pid(after_kill)
        assert replacement_pid != killed_pid
        assert worker_proc.poll() is None
        assert not list(Path(worker_tmp).rglob("*.partd"))
    finally:
        if async_engine is not None:
            asyncio.run(async_engine.dispose())
        worker_log_file.flush()
        worker_log_file.close()
        if worker_proc is not None:
            worker_proc.terminate()
            try:
                worker_proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                worker_proc.kill()
                worker_proc.wait(timeout=10)
        test_engine.dispose()
        try:
            import shutil

            shutil.rmtree(worker_tmp, ignore_errors=True)
        except OSError:
            pass
        if os.path.exists(worker_log_path):
            try:
                os.remove(worker_log_path)
            except OSError:
                pass
        with admin_engine.connect() as conn:
            conn.execute(
                text(
                    """
                    SELECT pg_terminate_backend(pid)
                    FROM pg_stat_activity
                    WHERE datname = :db_name
                      AND pid <> pg_backend_pid()
                    """
                ),
                {"db_name": test_db_name},
            )
            conn.execute(text(f'DROP DATABASE IF EXISTS "{test_db_name}"'))
        admin_engine.dispose()
