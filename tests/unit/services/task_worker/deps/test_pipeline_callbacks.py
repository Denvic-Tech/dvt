from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services.task_worker.deps import pipeline_callbacks

from src import enums
from src.pipeline.execution_mode import PipelineExecutionMode


class _FakeRedisClient:
    def __init__(self, label: str):
        self.label = label
        self.closed = False

    async def aclose(self):
        self.closed = True


@pytest.mark.asyncio
async def test_get_redis_reuses_client_per_loop(monkeypatch):
    created: list[_FakeRedisClient] = []

    def _from_url(_url: str):
        client = _FakeRedisClient(label=f"client-{len(created)}")
        created.append(client)
        return client

    await pipeline_callbacks.close_redis_clients()
    monkeypatch.setattr(pipeline_callbacks.redis, "from_url", _from_url)

    try:
        first = await pipeline_callbacks.get_redis()
        second = await pipeline_callbacks.get_redis()

        assert first is second
        assert len(created) == 1
    finally:
        await pipeline_callbacks.close_redis_clients()


@pytest.mark.asyncio
async def test_close_redis_clients_clears_cached_clients(monkeypatch):
    created: list[_FakeRedisClient] = []

    def _from_url(_url: str):
        client = _FakeRedisClient(label=f"client-{len(created)}")
        created.append(client)
        return client

    await pipeline_callbacks.close_redis_clients()
    monkeypatch.setattr(pipeline_callbacks.redis, "from_url", _from_url)

    try:
        first = await pipeline_callbacks.get_redis()
        await pipeline_callbacks.close_redis_clients()
        second = await pipeline_callbacks.get_redis()

        assert first is not second
        assert len(created) == 2
        assert created[0].closed is True
        assert created[1].closed is False
    finally:
        await pipeline_callbacks.close_redis_clients()

    assert created[1].closed is True


@pytest.mark.asyncio
async def test_on_node_error_sends_error_message_in_node_execution_status_event(monkeypatch):
    captured_payloads = []

    async def _fake_send_event(payload):
        captured_payloads.append(payload)

    monkeypatch.setattr(pipeline_callbacks, "send_event", _fake_send_event)
    monkeypatch.setattr(pipeline_callbacks, "get_worker_id", lambda: "worker-1")

    node = SimpleNamespace(_node_id="node-1", execution_mode=PipelineExecutionMode.FULL)
    await pipeline_callbacks.on_node_error(
        user_id="user-1",
        project_id="project-1",
        task_id="task-1",
        node=node,
        message="Ошибка выполнения SQL",
    )

    assert len(captured_payloads) == 1
    payload = captured_payloads[0]

    assert payload.worker_id == "worker-1"
    assert isinstance(payload.event, pipeline_callbacks.NodeExecutionStatusEvent)
    assert payload.event.status == enums.ExecutionStatus.ERROR
    assert payload.event.message == "Ошибка выполнения SQL"


@pytest.mark.asyncio
async def test_send_task_execution_telemetry_emits_telemetry_event(monkeypatch):
    captured_payloads = []

    async def _fake_send_event(payload):
        captured_payloads.append(payload)

    monkeypatch.setattr(pipeline_callbacks, "send_event", _fake_send_event)
    monkeypatch.setattr(pipeline_callbacks, "get_worker_id", lambda: "worker-1")

    task = SimpleNamespace(
        user_id="user-1",
        project_id="project-1",
        task_id="task-1",
    )
    await pipeline_callbacks.send_task_execution_telemetry(
        task,
        hostname="host-1",
        pid=123,
        rss_bytes=2048,
        memory_limit_bytes=4096,
        system_ram_used_percent=83.3,
    )

    assert len(captured_payloads) == 1
    payload = captured_payloads[0]
    assert payload.worker_id == "worker-1"
    assert isinstance(payload.event, pipeline_callbacks.TaskExecutionTelemetryEvent)
    assert payload.event.hostname == "host-1"
    assert payload.event.pid == 123
    assert payload.event.rss_bytes == 2048
    assert payload.event.memory_limit_bytes == 4096


@pytest.mark.asyncio
async def test_on_node_metadata_catalog_commits_when_datasets_updated(monkeypatch):
    import src.db
    from src.modules import data_catalog

    class _Session:
        def __init__(self):
            self.commit = AsyncMock()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

    sessions = []

    def session_factory():
        session = _Session()
        sessions.append(session)
        return session

    record = AsyncMock(return_value=SimpleNamespace(dataset_ids=("d1",), trusted_types=True))
    monkeypatch.setattr(src.db, "AsyncSessionLocal", session_factory)
    monkeypatch.setattr(data_catalog, "record_observed_node_metadata", record)

    node = SimpleNamespace(_node_id="node-1")
    await pipeline_callbacks.on_node_metadata_catalog(
        user_id="u", project_id="p", task_id="t", node=node, metadata={"output": None}, extra="ignored"
    )

    record.assert_awaited_once_with(session=sessions[0], project_id="p", node=node, metadata={"output": None})
    sessions[0].commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_on_node_metadata_catalog_swallows_failures(monkeypatch):
    import src.db
    from src.modules import data_catalog

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

    monkeypatch.setattr(src.db, "AsyncSessionLocal", _Session)
    monkeypatch.setattr(
        data_catalog, "record_observed_node_metadata", AsyncMock(side_effect=RuntimeError("catalog down"))
    )

    await pipeline_callbacks.on_node_metadata_catalog(
        user_id="u", project_id="p", task_id="t", node=SimpleNamespace(_node_id="n"), metadata={}
    )
