from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from services.installation_manager.api import build_router
from services.installation_manager.domain.models import Job, JobKind, JobState
from services.installation_manager.infrastructure.job_store import InMemoryJobStore


def _app(jobs: InMemoryJobStore) -> FastAPI:
    app = FastAPI()
    app.include_router(
        build_router(
            settings=MagicMock(),
            install_use_case=MagicMock(),
            update_use_case=MagicMock(),
            status_service=MagicMock(),
            jobs=jobs,
            library=MagicMock(),
        )
    )
    return app


@pytest.mark.asyncio
async def test_current_job_summary_returns_no_logs_or_steps() -> None:
    jobs = InMemoryJobStore()
    job = Job(JobKind.UPDATE, [("pull", "Pull images")])
    job.version = "1.2.3"
    job.log("sensitive log line")
    jobs.start(job)

    async with AsyncClient(
        transport=ASGITransport(app=_app(jobs)),
        base_url="http://test",
    ) as client:
        response = await client.get("/api/jobs/current/summary")

    assert response.status_code == 200
    assert response.json() == {
        "id": job.id,
        "kind": "update",
        "state": "running",
        "version": "1.2.3",
        "started_at": job.started_at.isoformat(),
        "finished_at": None,
    }
    assert "log" not in response.json()
    assert "steps" not in response.json()


@pytest.mark.asyncio
@pytest.mark.parametrize("state", [JobState.SUCCEEDED, JobState.FAILED])
async def test_current_job_summary_returns_terminal_state(state: JobState) -> None:
    jobs = InMemoryJobStore()
    job = Job(JobKind.UPDATE, [])
    jobs.start(job)
    job.finish(state)

    async with AsyncClient(
        transport=ASGITransport(app=_app(jobs)),
        base_url="http://test",
    ) as client:
        response = await client.get("/api/jobs/current/summary")

    assert response.status_code == 200
    assert response.json()["state"] == state.value
    assert response.json()["finished_at"] is not None


@pytest.mark.asyncio
async def test_current_job_summary_returns_404_without_job() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=_app(InMemoryJobStore())),
        base_url="http://test",
    ) as client:
        response = await client.get("/api/jobs/current/summary")

    assert response.status_code == 404
