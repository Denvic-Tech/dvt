"""HTTP API сервиса установки/обновления DVT."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from .application.install import InstallUseCase
from .application.status import StatusService
from .application.update import UpdateUseCase
from .config import Settings
from .domain import services as domain
from .domain.models import InstallConfig, UpdateConfig
from .domain.ports import DvtLibrary
from .infrastructure.job_store import InMemoryJobStore, JobAlreadyRunning
from .schemas import (
    InstallRequest,
    JobStatusResponse,
    JobSummaryResponse,
    SecretsResponse,
    UpdateRequest,
    UpdateResponse,
)


def build_router(
    settings: Settings,  # noqa: ARG001
    install_use_case: InstallUseCase,
    update_use_case: UpdateUseCase,
    status_service: StatusService,
    jobs: InMemoryJobStore,
    library: DvtLibrary,  # noqa: ARG001 - retained for composition compatibility
) -> APIRouter:
    router = APIRouter()

    def _start_update(data: UpdateRequest) -> UpdateResponse:
        try:
            job = update_use_case.start(
                UpdateConfig(
                    version=data.version,
                    ai_mcp_enabled=data.ai_mcp_enabled,
                    ai_mcp_internal_secret=data.ai_mcp_internal_secret,
                )
            )
        except JobAlreadyRunning as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            ) from exc
        return UpdateResponse(message="Update started", version=data.version, job_id=job.id)

    @router.get("/api/state")
    def get_state() -> dict:
        return status_service.state()

    @router.get("/api/config")
    def get_config() -> dict:
        return status_service.form_config()

    @router.get("/api/secrets", response_model=SecretsResponse)
    def new_secrets() -> SecretsResponse:
        return SecretsResponse(
            password=domain.generate_password(),
            token=domain.generate_password(),
            fernet_key=domain.generate_fernet_key(),
        )

    @router.post("/api/install", status_code=status.HTTP_202_ACCEPTED)
    def start_install(data: InstallRequest) -> dict:
        cfg = InstallConfig(
            version=data.version,
            public_urls=data.public_urls,
            postgres_user=data.postgres_user or "dvt-user",
            postgres_db=data.postgres_db or "DVT",
            postgres_password=data.postgres_password,
            valkey_password=data.valkey_password,
            valkey_db=data.valkey_db or "0",
            grpc_token=data.grpc_token,
            fernet_key=data.fernet_key,
            ai_mcp_enabled=data.ai_mcp_enabled,
            ai_mcp_internal_secret=data.ai_mcp_internal_secret,
            external_port=data.external_port or "80",
            task_workers_count=data.task_workers_count,
        )
        try:
            job = install_use_case.start(cfg)
        except JobAlreadyRunning as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            ) from exc
        return {"job_id": job.id}

    @router.post(
        "/api/update", response_model=UpdateResponse, status_code=status.HTTP_202_ACCEPTED
    )
    def start_update(data: UpdateRequest) -> UpdateResponse:
        return _start_update(data)

    @router.get("/api/jobs/current", response_model=JobStatusResponse)
    def current_job(log_offset: int = Query(default=0, ge=0)) -> dict:
        job = jobs.current()
        if job is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Установка или обновление ещё не запускались",
            )
        return job.snapshot(log_offset=log_offset)

    @router.get("/api/jobs/current/summary", response_model=JobSummaryResponse)
    def current_job_summary() -> dict:
        job = jobs.current()
        if job is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Установка или обновление ещё не запускались",
            )
        return job.summary()

    @router.post("/update", response_model=UpdateResponse, status_code=status.HTTP_202_ACCEPTED)
    def legacy_update(data: UpdateRequest) -> UpdateResponse:
        return _start_update(data)

    return router
