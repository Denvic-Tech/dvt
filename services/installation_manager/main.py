"""Точка входа: сборка зависимостей (composition root) и приложение FastAPI."""

from __future__ import annotations

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .api import build_router
from .application.install import InstallUseCase
from .application.status import StatusService
from .application.update import UpdateUseCase
from .config import load_settings
from .infrastructure.docker_cli import DockerCliGateway
from .infrastructure.dvt_lib import MountedDvtLibrary
from .infrastructure.job_store import InMemoryJobStore
from .logger import logger

settings = load_settings()

docker = DockerCliGateway()
library = MountedDvtLibrary(settings.lib_mount)
jobs = InMemoryJobStore()

install_use_case = InstallUseCase(settings, docker, library, jobs)
update_use_case = UpdateUseCase(settings, docker, library, jobs)
status_service = StatusService(settings, docker, library)

app = FastAPI(title="DVT Install & Update Service", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(
    build_router(
        settings=settings,
        install_use_case=install_use_case,
        update_use_case=update_use_case,
        status_service=status_service,
        jobs=jobs,
        library=library,
    )
)

if settings.static_dir is not None and settings.static_dir.is_dir():
    app.mount("/", StaticFiles(directory=str(settings.static_dir), html=True), name="static")
else:
    logger.warning("Статика фронтенда не найдена (%s) — доступно только API", settings.static_dir)


def main() -> None:
    uvicorn.run(
        "services.installation_manager.main:app",
        host="0.0.0.0",
        port=8000,
    )
