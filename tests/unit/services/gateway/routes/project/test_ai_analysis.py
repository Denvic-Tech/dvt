from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest

from services.gateway.routes.impl import ai_analysis as ai_analysis_impl
from services.gateway.routes.impl.ai_analysis import (
    impl as ai_analysis_impl_module,
    mappers as ai_analysis_mappers,
    parsing as ai_analysis_parsing,
    payloads as ai_analysis_payloads,
)

from src.clients import ai_analysis_client as ai_analysis_client_module
from src.enums import AIAnalysisStatus
from src.models import AIAnalysisRequestRecord, LogRecord
from src.modules.pipeline_graph.infra.db_models import (
    GraphEdgeRecord,
    GraphNodeRecord,
)
from src.modules.project.infra.db_models import ProjectRecord
from src.modules.task_execution.domain.types import TaskExecutionStatus, TaskSource
from src.modules.task_execution.infra.db_models import TaskRecord
from src.modules.user.infra.db_models import UserRecord
from src.pipeline.execution_mode import PipelineExecutionMode
from src.schemas.http.ai_analysis import AIAnalysisCreateSchema
from src.schemas.http.ai_analysis_service import (
    AIServiceAnalysisRequestReadSchema,
    AIServiceLogErrorAnalysisCreateResponseSchema,
    AIServiceLogErrorAnalysisCreateSchema,
)

import config


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _repo_traceback_path(*parts: str) -> str:
    return str((config.PROJECT.ROOT_DIR.joinpath(*parts)).resolve())


def _outside_repo_traceback_path(*parts: str) -> str:
    return str((config.PROJECT.ROOT_DIR.parent.joinpath(*parts)).resolve())


class _AsyncSessionAdapter:
    def __init__(self, session):
        self._session = session

    def add(self, instance):
        self._session.add(instance)

    async def commit(self):
        self._session.commit()

    async def refresh(self, instance):
        self._session.refresh(instance)

    async def flush(self, objects=None):
        self._session.flush(objects)

    async def execute(self, statement):
        return self._session.execute(statement)


def _create_task(
    db_session,
    *,
    project: ProjectRecord,
    user: UserRecord,
    task_id: str | None = None,
    status: TaskExecutionStatus = TaskExecutionStatus.ERROR,
    mode: PipelineExecutionMode = PipelineExecutionMode.FULL,
    queued_at: datetime | None = None,
    message: str | None = "Validation error for node node-1 (ReadTableFromDBV3): Input 'table_name' is required.",
    termination_reason: str | None = None,
) -> TaskRecord:
    task = TaskRecord(
        task_id=task_id or str(uuid4()),
        project_id=project.id,
        user_id=user.id,
        organization_id=project.organization_id,
        mode=mode,
        force_exec=False,
        status=status,
        source=TaskSource.UI,
        message=message,
        termination_reason=termination_reason,
        queued_at=queued_at or _now(),
    )
    db_session.add(task)
    db_session.commit()
    db_session.refresh(task)
    return task


@pytest.fixture(autouse=True)
def enable_ai_analysis(monkeypatch):
    monkeypatch.setattr(config.AI_ANALYSIS, "ENABLED", True)
    monkeypatch.setattr(config.AI_ANALYSIS, "SERVICE_URL", "http://127.0.0.1:8228")


@pytest.mark.asyncio
async def test_create_ai_analysis_request_returns_accepted_and_can_poll(
    gateway_client,
    router_prefix,
    db_session,
    test_user,
    test_user_project,
    monkeypatch,
):
    async def noop_run(request_id: str) -> None:
        return None

    monkeypatch.setattr(ai_analysis_impl, "run_ai_analysis_request", noop_run)
    task = _create_task(
        db_session,
        project=test_user_project,
        user=test_user,
        message="task failed",
    )
    failed_node = GraphNodeRecord(
        ui_id="node-1",
        type="ReadTableFromDBV3",
        position_x=0,
        position_y=0,
        selected=False,
        name="ReadTableFromDBV3",
        display_name="Read table",
        project_id=test_user_project.id,
        organization_id=test_user.organization_id,
        user_id=test_user.id,
        input_values={},
    )
    db_session.add(failed_node)
    db_session.commit()

    response = await gateway_client.post(
        f"{router_prefix}/projects/{test_user_project.id}/ai/analyze",
        json={"task_id": task.task_id},
    )

    assert response.status_code == 202, response.json()
    assert response.headers["retry-after"] == "2"
    payload = response.json()
    assert payload["status"] == "queued"
    assert "selected_node_ids" not in AIAnalysisCreateSchema.model_fields

    stored = db_session.get(AIAnalysisRequestRecord, payload["request_id"])
    assert stored is not None
    assert stored.user_id == test_user.id
    assert stored.organization_id == test_user.organization_id
    assert stored.project_id == test_user_project.id
    assert stored.task_id == task.task_id
    assert stored.context is None

    poll = await gateway_client.get(
        f"{router_prefix}/projects/{test_user_project.id}/ai/analyze/{stored.id}",
    )
    assert poll.status_code == 200, poll.json()
    assert poll.headers["retry-after"] == "2"
    assert poll.json()["request_id"] == stored.id
    assert poll.json()["status"] == "queued"


@pytest.mark.asyncio
async def test_create_ai_analysis_request_uses_task_owner_as_request_user_for_admin(
    db_session,
    test_admin_user,
    test_user,
    test_user_project,
    monkeypatch,
):
    async def noop_run(request_id: str) -> None:
        return None

    monkeypatch.setattr(ai_analysis_impl, "run_ai_analysis_request", noop_run)
    task = _create_task(
        db_session,
        project=test_user_project,
        user=test_user,
        message="task failed",
    )
    failed_node = GraphNodeRecord(
        ui_id="node-1",
        type="ReadTableFromDBV3",
        position_x=0,
        position_y=0,
        selected=False,
        name="ReadTableFromDBV3",
        display_name="Read table",
        project_id=test_user_project.id,
        organization_id=test_user.organization_id,
        user_id=test_user.id,
        input_values={},
    )
    db_session.add(failed_node)
    db_session.commit()

    result = await ai_analysis_impl_module.create_ai_analysis_request_route_impl(
        session=_AsyncSessionAdapter(db_session),
        user=test_admin_user,
        project=test_user_project,
        data=AIAnalysisCreateSchema(task_id=task.task_id),
        accept_language=None,
    )

    stored = db_session.get(AIAnalysisRequestRecord, result.request_id)
    assert stored is not None
    assert stored.user_id == task.user_id


@pytest.mark.asyncio
async def test_create_ai_analysis_request_does_not_store_failed_node_in_context(
    gateway_client,
    router_prefix,
    db_session,
    test_user,
    test_user_project,
    monkeypatch,
):
    async def noop_run(request_id: str) -> None:
        return None

    monkeypatch.setattr(ai_analysis_impl, "run_ai_analysis_request", noop_run)
    task = _create_task(
        db_session,
        project=test_user_project,
        user=test_user,
        message="task failed",
        termination_reason="boom",
    )
    failed_node = GraphNodeRecord(
        ui_id="node-1",
        type="DataFrameExecCode",
        position_x=0,
        position_y=0,
        selected=False,
        name="DataFrameExecCode",
        display_name="Exec code",
        project_id=test_user_project.id,
        organization_id=test_user.organization_id,
        user_id=test_user.id,
        input_values={},
    )
    log_entry = LogRecord(
        level="ERROR",
        service_name="task-worker",
        message="Error executing node node-1 (DataFrameExecCode): boom",
        task_id=task.task_id,
        user_id=test_user.id,
        project_id=test_user_project.id,
        created_at=_now(),
    )
    db_session.add_all([failed_node, log_entry])
    db_session.commit()

    response = await gateway_client.post(
        f"{router_prefix}/projects/{test_user_project.id}/ai/analyze",
        json={"task_id": task.task_id},
    )

    assert response.status_code == 202, response.json()
    stored = db_session.get(AIAnalysisRequestRecord, response.json()["request_id"])
    assert stored is not None
    assert stored.task_id == task.task_id
    assert stored.context is None


@pytest.mark.asyncio
async def test_create_ai_analysis_request_accepts_tasks_without_failed_node_resolution(
    gateway_client,
    router_prefix,
    db_session,
    test_user,
    test_user_project,
    monkeypatch,
):
    async def noop_run(request_id: str) -> None:
        return None

    monkeypatch.setattr(ai_analysis_impl, "run_ai_analysis_request", noop_run)
    task = _create_task(
        db_session,
        project=test_user_project,
        user=test_user,
        message="failed with password=hidden",
    )

    response = await gateway_client.post(
        f"{router_prefix}/projects/{test_user_project.id}/ai/analyze",
        json={"task_id": task.task_id},
    )

    assert response.status_code == 202, response.json()
    stored = db_session.get(AIAnalysisRequestRecord, response.json()["request_id"])
    assert stored is not None
    assert stored.task_id == task.task_id
    assert stored.context is None


@pytest.mark.asyncio
async def test_create_ai_analysis_request_returns_not_found_when_feature_disabled(
    gateway_client,
    router_prefix,
    db_session,
    test_user,
    test_user_project,
    monkeypatch,
):
    monkeypatch.setattr(config.AI_ANALYSIS, "ENABLED", False)
    task = _create_task(db_session, project=test_user_project, user=test_user)

    response = await gateway_client.post(
        f"{router_prefix}/projects/{test_user_project.id}/ai/analyze",
        json={"task_id": task.task_id},
    )

    assert response.status_code == 404
    assert db_session.query(AIAnalysisRequestRecord).count() == 0


@pytest.mark.asyncio
async def test_create_ai_analysis_request_rejects_missing_task(
    gateway_client,
    router_prefix,
    test_user_project,
):
    response = await gateway_client.post(
        f"{router_prefix}/projects/{test_user_project.id}/ai/analyze",
        json={"task_id": "missing-task"},
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_create_ai_analysis_request_rejects_non_failed_task(
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
        status=TaskExecutionStatus.SUCCESS,
    )

    response = await gateway_client.post(
        f"{router_prefix}/projects/{test_user_project.id}/ai/analyze",
        json={"task_id": task.task_id},
    )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_create_ai_analysis_request_rejects_metadata_only_task(
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
        mode=PipelineExecutionMode.METADATA_ONLY,
    )

    response = await gateway_client.post(
        f"{router_prefix}/projects/{test_user_project.id}/ai/analyze",
        json={"task_id": task.task_id},
    )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_poll_ai_analysis_request_respects_project_access_scope(
    gateway_client,
    router_prefix,
    db_session,
    test_admin_user,
    test_user_project,
):
    request = AIAnalysisRequestRecord(
        task_id="task-1",
        project_id=test_user_project.id,
        user_id=test_admin_user.id,
        organization_id=test_user_project.organization_id,
        status=AIAnalysisStatus.QUEUED,
    )
    db_session.add(request)
    db_session.commit()

    response = await gateway_client.get(
        f"{router_prefix}/projects/{test_user_project.id}/ai/analyze/{request.id}",
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_list_ai_analysis_requests_returns_user_history(
    gateway_client,
    router_prefix,
    db_session,
    test_user,
    test_user_project,
):
    older = AIAnalysisRequestRecord(
        task_id="older-task",
        project_id=test_user_project.id,
        user_id=test_user.id,
        organization_id=test_user.organization_id,
        status=AIAnalysisStatus.SUCCESS,
    )
    newer = AIAnalysisRequestRecord(
        task_id="newer-task",
        project_id=test_user_project.id,
        user_id=test_user.id,
        organization_id=test_user.organization_id,
        status=AIAnalysisStatus.ERROR,
        error="failed",
    )
    db_session.add_all([older, newer])
    db_session.commit()

    response = await gateway_client.get(
        f"{router_prefix}/projects/{test_user_project.id}/ai/analyze",
        params={"limit": 1, "offset": 0},
    )

    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["total"] == 2
    assert payload["limit"] == 1
    assert len(payload["items"]) == 1
    assert payload["items"][0]["task_id"] == "newer-task"


@pytest.mark.asyncio
async def test_list_ai_analysis_requests_filters_by_status_and_task_id(
    gateway_client,
    router_prefix,
    db_session,
    test_user,
    test_user_project,
):
    first = AIAnalysisRequestRecord(
        task_id="target-task",
        project_id=test_user_project.id,
        user_id=test_user.id,
        organization_id=test_user.organization_id,
        status=AIAnalysisStatus.SUCCESS,
    )
    second = AIAnalysisRequestRecord(
        task_id="target-task",
        project_id=test_user_project.id,
        user_id=test_user.id,
        organization_id=test_user.organization_id,
        status=AIAnalysisStatus.ERROR,
    )
    db_session.add_all([first, second])
    db_session.commit()

    response = await gateway_client.get(
        f"{router_prefix}/projects/{test_user_project.id}/ai/analyze",
        params={"status": "success", "task_id": "target-task"},
    )

    assert response.status_code == 200, response.json()
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["status"] == "success"


@pytest.mark.asyncio
async def test_list_ai_analysis_requests_refreshes_non_terminal_items_on_current_page_only(
    gateway_client,
    router_prefix,
    db_session,
    test_user,
    test_user_project,
    monkeypatch,
):
    page_item_one = AIAnalysisRequestRecord(
        task_id="task-1",
        project_id=test_user_project.id,
        user_id=test_user.id,
        organization_id=test_user.organization_id,
        status=AIAnalysisStatus.QUEUED,
        ai_service_request_id="remote-1",
        created_at=datetime(2026, 5, 19, 10, 0, 3, tzinfo=UTC),
        updated_at=datetime(2026, 5, 19, 10, 0, 3, tzinfo=UTC),
    )
    page_item_two = AIAnalysisRequestRecord(
        task_id="task-2",
        project_id=test_user_project.id,
        user_id=test_user.id,
        organization_id=test_user.organization_id,
        status=AIAnalysisStatus.RUNNING,
        ai_service_request_id="remote-2",
        created_at=datetime(2026, 5, 19, 10, 0, 2, tzinfo=UTC),
        updated_at=datetime(2026, 5, 19, 10, 0, 2, tzinfo=UTC),
    )
    off_page_item = AIAnalysisRequestRecord(
        task_id="task-3",
        project_id=test_user_project.id,
        user_id=test_user.id,
        organization_id=test_user.organization_id,
        status=AIAnalysisStatus.QUEUED,
        ai_service_request_id="remote-3",
        created_at=datetime(2026, 5, 19, 10, 0, 1, tzinfo=UTC),
        updated_at=datetime(2026, 5, 19, 10, 0, 1, tzinfo=UTC),
    )
    db_session.add_all([page_item_one, page_item_two, off_page_item])
    db_session.commit()
    for item in (page_item_one, page_item_two, off_page_item):
        db_session.refresh(item)

    requested_ids: list[str] = []

    class FakeResponse:
        def __init__(self, payload: dict[str, object]):
            self.status_code = 200
            self._payload = payload
            self.text = str(payload)
            self.request = httpx.Request("GET", "http://127.0.0.1:8228/v1/analysis/requests")

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url, headers, params=None):
            assert url == "http://127.0.0.1:8228/v1/analysis/requests"
            request_ids = [value for key, value in (params or []) if key == "request_id"]
            requested_ids.extend(request_ids)
            return FakeResponse(
                {
                    "items": [
                        {
                            "request_id": request_id,
                            "found": True,
                            "request": {
                                "request_id": request_id,
                                "status": "success",
                                "analysis_type": "log_error",
                                "created_at": _now().isoformat(),
                                "started_at": _now().isoformat(),
                                "finished_at": _now().isoformat(),
                                "result": {
                                    "title": f"Заголовок {request_id[-1]}",
                                    "classification": "user_pipeline_error",
                                    "severity": "low",
                                    "summary": f"Summary {request_id}",
                                    "details": f"Details {request_id}",
                                },
                                "error": None,
                            },
                        }
                        for request_id in request_ids
                    ]
                },
            )

    monkeypatch.setattr(ai_analysis_client_module.httpx, "AsyncClient", FakeClient)

    response = await gateway_client.get(
        f"{router_prefix}/projects/{test_user_project.id}/ai/analyze",
        params={"limit": 2, "offset": 0},
    )

    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["total"] == 3
    assert [item["request_id"] for item in payload["items"]] == [page_item_one.id, page_item_two.id]
    assert all(item["status"] == "success" for item in payload["items"])
    assert [item["title"] for item in payload["items"]] == ["Заголовок 1", "Заголовок 2"]
    assert requested_ids == ["remote-1", "remote-2"]

    db_session.refresh(page_item_one)
    db_session.refresh(page_item_two)
    db_session.refresh(off_page_item)
    assert page_item_one.status == AIAnalysisStatus.SUCCESS
    assert page_item_two.status == AIAnalysisStatus.SUCCESS
    assert off_page_item.status == AIAnalysisStatus.QUEUED


@pytest.mark.asyncio
async def test_list_ai_analysis_requests_keeps_response_when_one_refresh_fails(
    gateway_client,
    router_prefix,
    db_session,
    test_user,
    test_user_project,
    monkeypatch,
):
    first = AIAnalysisRequestRecord(
        task_id="task-1",
        project_id=test_user_project.id,
        user_id=test_user.id,
        organization_id=test_user.organization_id,
        status=AIAnalysisStatus.QUEUED,
        ai_service_request_id="remote-1",
        created_at=datetime(2026, 5, 19, 10, 1, 2, tzinfo=UTC),
        updated_at=datetime(2026, 5, 19, 10, 1, 2, tzinfo=UTC),
    )
    second = AIAnalysisRequestRecord(
        task_id="task-2",
        project_id=test_user_project.id,
        user_id=test_user.id,
        organization_id=test_user.organization_id,
        status=AIAnalysisStatus.RUNNING,
        ai_service_request_id="remote-2",
        created_at=datetime(2026, 5, 19, 10, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 5, 19, 10, 1, 1, tzinfo=UTC),
    )
    db_session.add_all([first, second])
    db_session.commit()
    db_session.refresh(first)
    db_session.refresh(second)

    class FakeResponse:
        def __init__(self, status_code: int, payload: dict[str, object]):
            self.status_code = status_code
            self._payload = payload
            self.text = str(payload)
            self.request = httpx.Request("GET", "http://127.0.0.1:8228/v1/analysis/requests")

        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError(
                    "request failed",
                    request=self.request,
                    response=httpx.Response(self.status_code, request=self.request, json=self._payload),
                )

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url, headers, params=None):
            assert url == "http://127.0.0.1:8228/v1/analysis/requests"
            request_ids = [value for key, value in (params or []) if key == "request_id"]
            return FakeResponse(
                200,
                {
                    "items": [
                        {
                            "request_id": "remote-1",
                            "found": True,
                            "request": {
                                "request_id": "remote-1",
                                "status": "success",
                                "analysis_type": "log_error",
                                "created_at": _now().isoformat(),
                                "started_at": _now().isoformat(),
                                "finished_at": _now().isoformat(),
                                "result": {
                                    "title": "Сбой сети",
                                    "classification": "infra_error",
                                    "severity": "medium",
                                    "summary": "Recovered",
                                    "details": "First item refreshed.",
                                },
                                "error": None,
                            },
                        },
                        {
                            "request_id": "remote-2",
                            "found": "remote-2" not in request_ids,
                            "request": None,
                        },
                    ]
                },
            )

    monkeypatch.setattr(ai_analysis_client_module.httpx, "AsyncClient", FakeClient)

    response = await gateway_client.get(
        f"{router_prefix}/projects/{test_user_project.id}/ai/analyze",
        params={"limit": 20, "offset": 0},
    )

    assert response.status_code == 200, response.json()
    payload = response.json()
    items_by_id = {item["request_id"]: item for item in payload["items"]}
    assert items_by_id[first.id]["status"] == "success"
    assert items_by_id[second.id]["status"] == "running"

    db_session.refresh(first)
    db_session.refresh(second)
    assert first.status == AIAnalysisStatus.SUCCESS
    assert second.status == AIAnalysisStatus.RUNNING


@pytest.mark.asyncio
async def test_get_ai_analysis_request_returns_stored_result_as_is(
    gateway_client,
    router_prefix,
    db_session,
    test_user,
    test_user_project,
):
    request = AIAnalysisRequestRecord(
        task_id="task-1",
        project_id=test_user_project.id,
        user_id=test_user.id,
        organization_id=test_user.organization_id,
        status=AIAnalysisStatus.SUCCESS,
        title="Сбой шлюза",
        result={
            "title": "Сбой шлюза",
            "classification": "dvt_bug",
            "severity": "high",
            "summary": "Gateway failed",
            "details": "Remote service marked this as DVT bug.",
            "bug_report_suggested": True,
        },
    )
    db_session.add(request)
    db_session.commit()

    response = await gateway_client.get(
        f"{router_prefix}/projects/{test_user_project.id}/ai/analyze/{request.id}",
    )

    assert response.status_code == 200, response.json()
    assert response.json()["title"] == "Сбой шлюза"
    assert response.json()["result"]["classification"] == "dvt_bug"
    assert response.json()["result"]["bug_report_suggested"] is True


@pytest.mark.asyncio
async def test_get_ai_analysis_request_refreshes_non_terminal_state_from_external_service(
    gateway_client,
    router_prefix,
    db_session,
    test_user,
    test_user_project,
    monkeypatch,
):
    request = AIAnalysisRequestRecord(
        task_id="task-1",
        project_id=test_user_project.id,
        user_id=test_user.id,
        organization_id=test_user.organization_id,
        status=AIAnalysisStatus.QUEUED,
        ai_service_request_id="remote-1",
    )
    db_session.add(request)
    db_session.commit()
    db_session.refresh(request)

    class FakeResponse:
        def __init__(self, status_code: int, payload: dict[str, object]):
            self.status_code = status_code
            self._payload = payload
            self.text = str(payload)
            self.request = httpx.Request("GET", "http://127.0.0.1:8228")

        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError(
                    "request failed",
                    request=self.request,
                    response=httpx.Response(self.status_code, request=self.request, json=self._payload),
                )

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url, headers, params=None):
            assert url == "http://127.0.0.1:8228/v1/analysis/requests/remote-1"
            assert headers["Content-Type"] == "application/json"
            assert params is None
            return FakeResponse(
                200,
                {
                    "request_id": "remote-1",
                    "status": "success",
                    "analysis_type": "log_error",
                    "created_at": _now().isoformat(),
                    "started_at": _now().isoformat(),
                    "finished_at": _now().isoformat(),
                    "result": {
                        "title": "Сбой сети",
                        "classification": "infra_error",
                        "severity": "medium",
                        "summary": "Recovered",
                        "details": "Remote result fetched on GET.",
                    },
                    "error": None,
                },
            )

    monkeypatch.setattr(ai_analysis_client_module.httpx, "AsyncClient", FakeClient)

    response = await gateway_client.get(
        f"{router_prefix}/projects/{test_user_project.id}/ai/analyze/{request.id}",
    )

    assert response.status_code == 200, response.json()
    assert response.json()["status"] == "success"
    assert response.json()["title"] == "Сбой сети"
    assert response.json()["result"]["classification"] == "infra_error"

    db_session.refresh(request)
    assert request.status == AIAnalysisStatus.SUCCESS
    assert request.title == "Сбой сети"
    assert request.result["classification"] == "infra_error"
    assert request.finished_at is not None


@pytest.mark.asyncio
async def test_run_ai_analysis_request_calls_external_ai_service_and_stores_result(
    db_session,
    test_user,
    test_user_project,
    monkeypatch,
):
    traceback_text = (
        "Traceback (most recent call last):\n"
        f'  File "{_repo_traceback_path("src", "pipeline", "processor.py")}", line 518, in _process_node\n'
        '    raise ValueError("boom")\n'
        "ValueError: boom"
    )
    task = _create_task(
        db_session,
        project=test_user_project,
        user=test_user,
        task_id="failed-task",
        message="Validation error for node node-1 (ReadTableFromDBV3): Input 'table_name' is required.",
        termination_reason=traceback_text,
    )
    upstream_node = GraphNodeRecord(
        ui_id="node-0",
        type="ReadTableFromDBV3",
        position_x=0,
        position_y=0,
        selected=False,
        name="ReadTableFromDBV3",
        display_name="Source table",
        project_id=test_user_project.id,
        organization_id=test_user.organization_id,
        user_id=test_user.id,
        input_values={"table_name": {"__dvt_type": "const", "value": "orders"}},
    )
    failed_node = GraphNodeRecord(
        ui_id="node-1",
        type="ReadTableFromDBV3",
        position_x=0,
        position_y=0,
        selected=False,
        name="ReadTableFromDBV3",
        display_name="Read table",
        project_id=test_user_project.id,
        organization_id=test_user.organization_id,
        user_id=test_user.id,
        input_values={"table_name": {"__dvt_type": "const", "value": ""}},
    )
    edge = GraphEdgeRecord(
        ui_id="edge-1",
        type="default",
        source="node-0",
        source_handle="output-output",
        target="node-1",
        target_handle="input-table_name",
        project_id=test_user_project.id,
        organization_id=test_user.organization_id,
        user_id=test_user.id,
    )
    log_entry = LogRecord(
        level="ERROR",
        service_name="gateway",
        message="Validation error for node node-1 (ReadTableFromDBV3): Input 'table_name' is required.",
        exception_traceback=traceback_text,
        task_id=task.task_id,
        user_id=test_user.id,
        module="pipeline.processor",
        function="_process_node",
        line=518,
        created_at=_now(),
    )
    request = AIAnalysisRequestRecord(
        task_id=task.task_id,
        project_id=test_user_project.id,
        user_id=test_user.id,
        organization_id=test_user.organization_id,
        status=AIAnalysisStatus.QUEUED,
    )
    db_session.add_all([upstream_node, failed_node, edge, log_entry, request])
    db_session.commit()
    db_session.refresh(request)

    captured: dict[str, object] = {}
    get_calls = 0

    class FakeResponse:
        def __init__(self, status_code: int, payload: dict[str, object]):
            self.status_code = status_code
            self._payload = payload
            self.text = str(payload)
            self.request = httpx.Request("GET", "http://127.0.0.1:8228")

        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError(
                    "request failed",
                    request=self.request,
                    response=httpx.Response(self.status_code, request=self.request, json=self._payload),
                )

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self, timeout):
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, headers, json):
            captured["create_url"] = url
            captured["headers"] = headers
            captured["payload"] = json
            return FakeResponse(
                202,
                {"request_id": "remote-1", "status": "queued"},
            )

        async def get(self, url, headers, params=None):
            nonlocal get_calls
            get_calls += 1
            captured["poll_url"] = url
            captured["poll_headers"] = headers
            captured["poll_params"] = params
            if get_calls == 1:
                return FakeResponse(
                    200,
                    {
                        "request_id": "remote-1",
                        "status": "running",
                        "analysis_type": "log_error",
                        "created_at": _now().isoformat(),
                        "error": None,
                    },
                )
            return FakeResponse(
                200,
                {
                    "request_id": "remote-1",
                    "status": "success",
                    "analysis_type": "log_error",
                    "created_at": _now().isoformat(),
                    "started_at": _now().isoformat(),
                    "finished_at": _now().isoformat(),
                    "result": {
                        "title": "Нет ввода",
                        "classification": "user_pipeline_error",
                        "severity": "medium",
                        "summary": "Missing required input.",
                        "details": "table_name is required.",
                        "recommended_actions": [
                            {
                                "title": "Set table name",
                                "description": "Provide table_name in the node input.",
                            }
                        ],
                        "bug_report_suggested": False,
                    },
                    "error": None,
                },
            )

    class SessionContext:
        async def __aenter__(self):
            return _AsyncSessionAdapter(db_session)

        async def __aexit__(self, exc_type, exc, tb):
            return None

    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(ai_analysis_impl_module, "get_async_session_acm", lambda: SessionContext())
    monkeypatch.setattr(ai_analysis_client_module.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(ai_analysis_payloads, "get_version_from_pyproject", lambda: "1.2.3")
    monkeypatch.setattr(ai_analysis_impl_module.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(config.AI_ANALYSIS, "SERVICE_API_KEY", "secret-key")

    await ai_analysis_impl.run_ai_analysis_request(request.id)

    db_session.refresh(request)
    assert captured["create_url"] == "http://127.0.0.1:8228/v1/analysis/log-error"
    assert captured["headers"] == {
        "Content-Type": "application/json",
        "Authorization": "Bearer secret-key",
    }

    payload = captured["payload"]
    assert payload["idempotency_key"] == request.id
    assert payload["dvt_version"] == "1.2.3"
    assert payload["task"] == {
        "id": "failed-task",
        "status": "error",
        "mode": "full",
        "started_at": None,
        "finished_at": None,
    }
    assert payload["project"] == {"id": test_user_project.id, "name": test_user_project.name}
    assert payload["analysis_context"] == {"traceback_source_modules": ["src.pipeline.processor"]}
    assert payload["traceback"] == traceback_text
    assert payload["logs"] == [
        {
            "timestamp": log_entry.created_at.isoformat().replace("+00:00", "Z"),
            "level": "ERROR",
            "service": "gateway",
            "module": "pipeline.processor",
            "function": "_process_node",
            "line": 518,
            "message": "Validation error for node node-1 (ReadTableFromDBV3): Input 'table_name' is required.",
        }
    ]
    assert payload["pipeline_context"]["edges"] == [
        {
            "source_node_id": "node-0",
            "target_node_id": "node-1",
            "source_output": "output",
            "target_input": "table_name",
        }
    ]

    pipeline_nodes = {item["id"]: item for item in payload["pipeline_context"]["nodes"]}
    assert set(pipeline_nodes) == {"node-0", "node-1"}
    assert payload["pipeline_context"]["nodes"][-1]["id"] == "node-1"
    assert pipeline_nodes["node-1"]["upstream_node_ids"] == ["node-0"]
    assert pipeline_nodes["node-1"]["source_module"]
    assert pipeline_nodes["node-1"]["source_file"]
    assert "role" not in pipeline_nodes["node-0"]
    assert "role" not in pipeline_nodes["node-1"]

    assert captured["poll_url"] == "http://127.0.0.1:8228/v1/analysis/requests/remote-1"
    assert captured["poll_params"] is None
    assert request.ai_service_request_id == "remote-1"
    assert request.status == AIAnalysisStatus.SUCCESS
    assert request.title == "Нет ввода"
    assert request.result["classification"] == "user_pipeline_error"
    assert request.finished_at is not None


@pytest.mark.asyncio
async def test_run_ai_analysis_request_serializes_node_input_values_to_plain_json(
    db_session,
    test_user,
    test_user_project,
    monkeypatch,
):
    task = _create_task(
        db_session,
        project=test_user_project,
        user=test_user,
        task_id="failed-task-json",
        message="Error executing node node-1 (DataFrameExecCode): boom",
    )
    failed_node = GraphNodeRecord(
        ui_id="node-1",
        type="DataFrameExecCode",
        position_x=0,
        position_y=0,
        selected=False,
        name="DataFrameExecCode",
        display_name="Exec code",
        project_id=test_user_project.id,
        organization_id=test_user.organization_id,
        user_id=test_user.id,
        input_values={
            "code": {"__dvt_type": "const", "value": "print('boom')"},
            "retries": {"__dvt_type": "const", "value": 1},
        },
    )
    request = AIAnalysisRequestRecord(
        task_id=task.task_id,
        project_id=test_user_project.id,
        user_id=test_user.id,
        organization_id=test_user.organization_id,
        status=AIAnalysisStatus.QUEUED,
    )
    db_session.add_all([failed_node, request])
    db_session.commit()
    db_session.refresh(request)

    class SessionContext:
        async def __aenter__(self):
            return _AsyncSessionAdapter(db_session)

        async def __aexit__(self, exc_type, exc, tb):
            return None

    captured_payload = {}

    async def fake_create_remote_analysis_request(
        payload: AIServiceLogErrorAnalysisCreateSchema,
    ) -> AIServiceLogErrorAnalysisCreateResponseSchema:
        captured_payload["payload"] = payload
        return AIServiceLogErrorAnalysisCreateResponseSchema(
            request_id="remote-serialized",
            status="queued",
        )

    async def fake_get_remote_analysis_request(_request_id: str) -> AIServiceAnalysisRequestReadSchema:
        return AIServiceAnalysisRequestReadSchema.model_validate(
            {
                "request_id": "remote-serialized",
                "status": "success",
                "analysis_type": "log_error",
                "created_at": _now().isoformat(),
                "started_at": _now().isoformat(),
                "finished_at": _now().isoformat(),
                "result": {
                    "title": "Сериализация",
                    "classification": "user_pipeline_error",
                    "severity": "low",
                    "summary": "serialized",
                    "details": "serialized",
                },
                "error": None,
            }
        )

    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(ai_analysis_impl_module, "get_async_session_acm", lambda: SessionContext())
    monkeypatch.setattr(
        ai_analysis_impl_module,
        "create_remote_analysis_request",
        fake_create_remote_analysis_request,
    )
    monkeypatch.setattr(
        ai_analysis_impl_module,
        "get_remote_analysis_request",
        fake_get_remote_analysis_request,
    )
    monkeypatch.setattr(ai_analysis_impl_module.asyncio, "sleep", no_sleep)

    await ai_analysis_impl.run_ai_analysis_request(request.id)

    node_payload = next(
        item
        for item in captured_payload["payload"].pipeline_context.nodes
        if item.id == "node-1"
    )
    assert node_payload.input_values == {
        "code": {"__dvt_type": "const", "value": "print('boom')"},
        "retries": {"__dvt_type": "const", "value": 1},
    }
    assert captured_payload["payload"].pipeline_context.nodes[-1].id == "node-1"


@pytest.mark.asyncio
async def test_build_pipeline_context_ignores_orphan_edges(
    db_session,
    test_user,
    test_user_project,
):
    source_node = GraphNodeRecord(
        ui_id="node-0",
        type="ReadTableFromDBV3",
        position_x=0,
        position_y=0,
        selected=False,
        name="ReadTableFromDBV3",
        display_name="Source table",
        project_id=test_user_project.id,
        organization_id=test_user.organization_id,
        user_id=test_user.id,
        input_values={},
    )
    target_node = GraphNodeRecord(
        ui_id="node-1",
        type="DataFrameExecCode",
        position_x=0,
        position_y=0,
        selected=False,
        name="DataFrameExecCode",
        display_name="Exec code",
        project_id=test_user_project.id,
        organization_id=test_user.organization_id,
        user_id=test_user.id,
        input_values={},
    )
    valid_edge = GraphEdgeRecord(
        ui_id="edge-1",
        type="default",
        source="node-0",
        source_handle="output-output",
        target="node-1",
        target_handle="input-code",
        project_id=test_user_project.id,
        organization_id=test_user.organization_id,
        user_id=test_user.id,
    )
    orphan_edge = GraphEdgeRecord(
        ui_id="edge-2",
        type="default",
        source="missing-node",
        source_handle="output-output",
        target="node-1",
        target_handle="input-code",
        project_id=test_user_project.id,
        organization_id=test_user.organization_id,
        user_id=test_user.id,
    )
    db_session.add_all([source_node, target_node, valid_edge, orphan_edge])
    db_session.commit()

    pipeline_context = await ai_analysis_payloads.build_pipeline_context(
        _AsyncSessionAdapter(db_session),
        project=test_user_project,
    )

    assert [edge.source_node_id for edge in pipeline_context.edges] == ["node-0"]
    assert [edge.target_node_id for edge in pipeline_context.edges] == ["node-1"]
    node_payloads = {node.id: node for node in pipeline_context.nodes}
    assert node_payloads["node-1"].upstream_node_ids == ["node-0"]


@pytest.mark.asyncio
async def test_run_ai_analysis_request_marks_error_on_remote_failure(
    db_session,
    test_user,
    test_user_project,
    monkeypatch,
):
    task = _create_task(db_session, project=test_user_project, user=test_user, task_id="failed-task")
    failed_node = GraphNodeRecord(
        ui_id="node-1",
        type="ReadTableFromDBV3",
        position_x=0,
        position_y=0,
        selected=False,
        name="ReadTableFromDBV3",
        display_name="Read table",
        project_id=test_user_project.id,
        organization_id=test_user.organization_id,
        user_id=test_user.id,
        input_values={},
    )
    request = AIAnalysisRequestRecord(
        task_id=task.task_id,
        project_id=test_user_project.id,
        user_id=test_user.id,
        organization_id=test_user.organization_id,
        status=AIAnalysisStatus.QUEUED,
    )
    db_session.add_all([failed_node, request])
    db_session.commit()
    db_session.refresh(request)

    class SessionContext:
        async def __aenter__(self):
            return _AsyncSessionAdapter(db_session)

        async def __aexit__(self, exc_type, exc, tb):
            return None

    async def fail_create(_: dict[str, object]) -> dict[str, object]:
        raise RuntimeError("remote create failed")

    monkeypatch.setattr(ai_analysis_impl_module, "get_async_session_acm", lambda: SessionContext())
    monkeypatch.setattr(ai_analysis_impl_module, "create_remote_analysis_request", fail_create)

    await ai_analysis_impl.run_ai_analysis_request(request.id)

    db_session.refresh(request)
    assert request.status == AIAnalysisStatus.ERROR
    assert request.error == "remote create failed"
    assert request.finished_at is not None

def test_extract_traceback_source_modules_filters_non_repo_paths():
    traceback_text = (
        "Traceback (most recent call last):\n"
        f'  File "{_repo_traceback_path("src", "pipeline", "processor.py")}", line 10, in run\n'
        f'  File "{_outside_repo_traceback_path("outside_repo", "lib.py")}", line 5, in helper\n'
        "RuntimeError: boom"
    )

    assert ai_analysis_parsing.extract_traceback_source_modules(traceback_text) == [
        "src.pipeline.processor"
    ]


def test_map_remote_status_handles_cancelled_and_unknown():
    assert ai_analysis_mappers.map_remote_status("cancelled") == (
        AIAnalysisStatus.ERROR,
        "AI service request was cancelled",
    )
    assert ai_analysis_mappers.map_remote_status("unexpected") == (AIAnalysisStatus.ERROR, None)


@pytest.mark.asyncio
async def test_build_remote_logs_returns_latest_entries_in_original_order(
    db_session,
    test_user,
    test_user_project,
):
    task = _create_task(
        db_session,
        project=test_user_project,
        user=test_user,
        task_id="logs-limit-task",
        message="task failed",
        termination_reason="task traceback fallback",
    )
    base_time = datetime(2026, 5, 19, 12, 0, 0, tzinfo=UTC)
    log_entries = [
        LogRecord(
            level="INFO",
            service_name="gateway",
            message=f"log-{index:03d}",
            task_id=task.task_id,
            user_id=test_user.id,
            project_id=test_user_project.id,
            created_at=base_time.replace(second=index % 60, minute=index // 60),
            exception_traceback="traceback-from-excluded-log" if index == 4 else None,
        )
        for index in range(105)
    ]
    log_entries.extend(
        [
            LogRecord(
                level="DEBUG",
                service_name="gateway",
                message="debug-old",
                task_id=task.task_id,
                user_id=test_user.id,
                project_id=test_user_project.id,
                created_at=datetime(2026, 5, 19, 11, 59, 58, tzinfo=UTC),
            ),
            LogRecord(
                level="DEBUG",
                service_name="gateway",
                message="debug-new",
                task_id=task.task_id,
                user_id=test_user.id,
                project_id=test_user_project.id,
                created_at=datetime(2026, 5, 19, 12, 2, 0, tzinfo=UTC),
            ),
        ]
    )
    db_session.add_all(log_entries)
    db_session.commit()

    logs, traceback_text = await ai_analysis_payloads.build_remote_logs(
        _AsyncSessionAdapter(db_session),
        task=task,
    )

    expected_info_messages = [
        f"log-{index:03d}" for index in range(105 - max(len(logs) - 1, 0), 105)
    ]
    assert [item.message for item in logs[:-1]] == expected_info_messages
    assert logs[-1].message == "debug-new"
    assert all(item.level == "INFO" for item in logs[:-1])
    assert logs[-1].level == "DEBUG"
    assert traceback_text == "traceback-from-excluded-log"
