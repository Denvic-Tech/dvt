"""Use case чтения текущего состояния: доступность Docker, установленная
версия и предзаполнение формы."""

from __future__ import annotations

from ..config import Settings
from ..domain import services as domain
from ..domain.ports import DockerGateway, DvtLibrary


class StatusService:
    def __init__(self, settings: Settings, docker: DockerGateway, library: DvtLibrary):
        self._settings = settings
        self._docker = docker
        self._lib = library

    def state(self) -> dict:
        docker_ok = self._docker.docker_available()
        env = self._lib.read_env()
        installed = self._lib.installed()
        project = env.get("COMPOSE_PROJECT_NAME") or self._settings.default_project_name
        running = docker_ok and self._docker.project_running(
            project, exclude_service=self._settings.self_service_name
        )
        return {
            "docker_available": docker_ok,
            "compose_available": self._docker.compose_available() if docker_ok else False,
            "installed": installed,
            "running": running,
            "current_version": env.get("DVT_VERSION", "") if installed else "",
            "lib_dir": self._settings.lib_dir_host,
            "public_urls": [u for u in env.get("DVT_PUBLIC_URL", "").split(";") if u],
            "external_port": env.get("DVT_EXTERNAL_PORT", "80"),
            "standalone": self._settings.standalone,
            "dev_mode": self._settings.dev_mode,
            "target_services": list(self._settings.target_services),
            "ai_mcp_enabled": domain.parse_bool_value(
                env.get("DVT_AI_MCP_ENABLED"), default=False
            ),
        }

    def form_config(self) -> dict:
        """Дефолты формы установки, дополненные существующим .env."""
        env = self._lib.read_env()
        installed = self._lib.installed()

        public_urls = [u for u in env.get("DVT_PUBLIC_URL", "").split(";") if u]
        try:
            workers = int(env.get("DVT_TASK_WORKERS_COUNT", "1"))
        except ValueError:
            workers = 1

        return {
            "is_update": installed,
            "lib_dir": self._settings.lib_dir_host,
            "version": env.get("DVT_VERSION", "latest"),
            "public_urls": public_urls or ["http://localhost"],
            "postgres_user": env.get("DVT_POSTGRES_USER", "dvt-user"),
            "postgres_db": env.get("DVT_POSTGRES_DB", "DVT"),
            "valkey_db": env.get("DVT_VALKEY_DB", "0"),
            "external_port": env.get("DVT_EXTERNAL_PORT", "80"),
            "task_workers_count": workers,
            "ai_mcp_enabled": domain.parse_bool_value(
                env.get("DVT_AI_MCP_ENABLED"), default=False
            ),
            # Секреты в браузер не отдаём — только флаги наличия
            "has_postgres_password": bool(env.get("DVT_POSTGRES_PASSWORD")),
            "has_valkey_password": bool(env.get("DVT_VALKEY_PASSWORD")),
            "has_grpc_token": bool(env.get("DVT_GRPC_FORWARD_SERVICE_TOKEN")),
            "has_fernet_key": bool(env.get("DVT_FERNET_KEY")),
            "has_ai_mcp_internal_secret": bool(env.get("DVT_AI_MCP_INTERNAL_SECRET")),
        }
