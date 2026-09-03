from __future__ import annotations

import httpx
import pytest

from src.clients.ai_analysis_client import AIAnalysisClient
from src.schemas.http.ai_analysis_service import (
    AIServiceAnalysisRequestBatchReadSchema,
    AIServiceAnalysisRequestReadSchema,
    AIServiceLogErrorAnalysisCreateResponseSchema,
    AIServiceLogErrorAnalysisCreateSchema,
)


def _build_create_payload() -> AIServiceLogErrorAnalysisCreateSchema:
    return AIServiceLogErrorAnalysisCreateSchema.model_validate(
        {
            "idempotency_key": "req-1",
            "dvt_version": "1.2.3",
            "task": {
                "id": "task-1",
                "status": "error",
                "mode": "full",
                "started_at": None,
                "finished_at": None,
            },
            "project": {
                "id": "project-1",
                "name": "Project 1",
            },
            "pipeline_context": {
                "nodes": [
                    {
                        "id": "node-1",
                        "name": "Source",
                        "type": "ReadTableFromDBV3",
                        "input_values": {},
                        "upstream_node_ids": [],
                        "source_module": "src.nodes.read_table",
                        "source_file": "src/nodes/read_table.py",
                    },
                    {
                        "id": "node-2",
                        "name": "Failed",
                        "type": "DataFrameExecCode",
                        "input_values": {"code": {"__dvt_type": "const", "value": "boom"}},
                        "upstream_node_ids": ["node-1"],
                        "source_module": "src.nodes.exec_code",
                        "source_file": "src/nodes/exec_code.py",
                    },
                ],
                "edges": [
                    {
                        "source_node_id": "node-1",
                        "target_node_id": "node-2",
                        "source_output": "output",
                        "target_input": "table_name",
                    }
                ],
            },
            "analysis_context": {
                "traceback_source_modules": ["src.pipeline.processor"],
            },
            "logs": [
                {
                    "timestamp": None,
                    "level": "ERROR",
                    "service": "gateway",
                    "module": "pipeline.processor",
                    "function": "_process_node",
                    "line": 42,
                    "message": "boom",
                }
            ],
            "traceback": "Traceback...",
        }
    )


class _FakeResponse:
    def __init__(self, payload: dict[str, object], *, status_code: int = 200, url: str = "http://test"):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)
        self.request = httpx.Request("GET", url)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "request failed",
                request=self.request,
                response=httpx.Response(self.status_code, request=self.request, json=self._payload),
            )

    def json(self) -> dict[str, object]:
        return self._payload


@pytest.mark.asyncio
async def test_ai_analysis_client_validates_create_response_schema(monkeypatch):
    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, headers, json):
            return _FakeResponse(
                {"request_id": "remote-1", "status": "queued"},
                url=url,
            )

    monkeypatch.setattr("src.clients.ai_analysis_client.httpx.AsyncClient", FakeClient)

    payload = _build_create_payload()
    result = await AIAnalysisClient().create_request(payload)

    assert isinstance(result, AIServiceLogErrorAnalysisCreateResponseSchema)
    assert result.request_id == "remote-1"
    assert result.status.value == "queued"


@pytest.mark.asyncio
async def test_ai_analysis_client_rejects_invalid_single_request_payload(monkeypatch):
    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url, headers, params=None):
            return _FakeResponse(
                {
                    "request_id": "remote-1",
                    "status": "success",
                    "analysis_type": "log_error",
                    "created_at": "2026-05-19T10:00:00+00:00",
                    "result": {
                        "title": "Сбой связи",
                        "classification": "infra_error",
                        "severity": "medium",
                        "summary": "Recovered",
                    },
                    "error": None,
                },
                url=url,
            )

    monkeypatch.setattr("src.clients.ai_analysis_client.httpx.AsyncClient", FakeClient)

    with pytest.raises(RuntimeError, match="invalid payload"):
        await AIAnalysisClient().get_request("remote-1")


@pytest.mark.asyncio
async def test_ai_analysis_client_validates_batch_response_schema(monkeypatch):
    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url, headers, params=None):
            return _FakeResponse(
                {
                    "items": [
                        {
                            "request_id": "remote-1",
                            "found": True,
                            "request": {
                                "request_id": "remote-1",
                                "status": "running",
                                "analysis_type": "log_error",
                                "created_at": "2026-05-19T10:00:00+00:00",
                                "started_at": "2026-05-19T10:00:01+00:00",
                                "finished_at": None,
                                "result": None,
                                "error": None,
                            },
                        }
                    ]
                },
                url=url,
            )

    monkeypatch.setattr("src.clients.ai_analysis_client.httpx.AsyncClient", FakeClient)

    result = await AIAnalysisClient().get_requests(["remote-1"])

    assert isinstance(result, AIServiceAnalysisRequestBatchReadSchema)
    assert result.items[0].request_id == "remote-1"
    assert isinstance(result.items[0].request, AIServiceAnalysisRequestReadSchema)
    assert result.items[0].request.status.value == "running"
