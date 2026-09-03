from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

_TRUE_TOKENS = {"1", "true", "yes", "on"}

DEFAULT_TARGET_SERVICES = "orchestrator;task-worker;project-scheduler;gateway;dvt-ai-mcp;ui;proxy"


@dataclass(frozen=True)
class Settings:
    # Каталог данных DVT: точка монтирования в контейнере и путь на хосте
    lib_mount: Path
    lib_dir_host: str

    # Внешние сервисы дистрибуции
    registry_url: str
    raw_storage_url: str

    # Compose
    default_project_name: str
    network_name: str
    target_services: tuple[str, ...]

    # Dev-режим: явные compose-файлы из репозитория (как старый update-service).
    # Если пусто — прод-режим: compose и .env берутся из lib_mount.
    compose_files: tuple[Path, ...]
    project_dir: Path | None
    update_mode: str  # "pull" | "build" (build имеет смысл только в dev-режиме)

    # Прочее
    standalone: bool
    static_dir: Path | None
    task_worker_service: str = "task-worker"
    self_service_name: str = "update-service"

    @property
    def dev_mode(self) -> bool:
        return bool(self.compose_files)


def load_settings() -> Settings:
    compose_files = tuple(
        Path(chunk.strip())
        for chunk in os.getenv("UPDATE_SERVICE_COMPOSE_FILES", "").split(";")
        if chunk.strip()
    )
    project_dir_raw = os.getenv("UPDATE_SERVICE_PROJECT_DIR", "")
    static_dir_raw = os.getenv("UPDATE_SERVICE_STATIC_DIR", "/app/static")

    return Settings(
        lib_mount=Path(os.getenv("UPDATE_SERVICE_LIB_MOUNT", "/dvt-lib")),
        lib_dir_host=os.getenv("DVT_LIB_DIR", "/var/lib/dvt"),
        registry_url=os.getenv("CONTAINER_REGISTRY_URL") or "cr.distribution.denvic.tech",
        raw_storage_url=os.getenv("RAW_STORAGE_URL", "https://raw.distribution.denvic.tech"),
        default_project_name=os.getenv("COMPOSE_PROJECT_NAME") or "dvt",
        network_name=os.getenv("DVT_NETWORK_NAME", "dvt-net"),
        target_services=tuple(
            chunk.strip()
            for chunk in os.getenv("UPDATE_SERVICE_TARGET_SERVICES", DEFAULT_TARGET_SERVICES).split(";")
            if chunk.strip()
        ),
        compose_files=compose_files,
        project_dir=Path(project_dir_raw) if project_dir_raw else None,
        update_mode=os.getenv("UPDATE_SERVICE_MODE", "pull"),
        standalone=os.getenv("UPDATE_SERVICE_STANDALONE", "false").lower() in _TRUE_TOKENS,
        static_dir=Path(static_dir_raw) if static_dir_raw else None,
    )
