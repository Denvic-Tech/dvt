"""Use case установки DVT на новую машину (аналог install.sh)."""

from __future__ import annotations

import threading
import time
import uuid

import httpx

from ..config import Settings
from ..domain import services as domain
from ..domain.models import InstallConfig, Job, JobKind, JobState
from ..domain.ports import DockerGateway, DvtLibrary
from ..infrastructure.job_store import InMemoryJobStore
from .base import StepError, run_step

INSTALL_STEPS = [
    ("check_docker", "Проверка Docker и Docker Compose"),
    ("prepare_dirs", "Создание каталогов данных"),
    ("initialize_identity", "Инициализация installation identity"),
    ("write_env", "Запись конфигурации (.env)"),
    ("download_compose", "Загрузка docker-compose.yaml"),
    ("create_network", "Создание сети"),
    ("compose_up", "Запуск сервисов DVT"),
]

MAX_COMPOSE_ATTEMPTS = 3


class InstallUseCase:
    def __init__(
        self,
        settings: Settings,
        docker: DockerGateway,
        library: DvtLibrary,
        jobs: InMemoryJobStore,
    ):
        self._settings = settings
        self._docker = docker
        self._lib = library
        self._jobs = jobs

    def start(self, cfg: InstallConfig) -> Job:
        self._prepare_config(cfg)
        job = Job(JobKind.INSTALL, INSTALL_STEPS)
        job.version = cfg.version
        self._jobs.start(job)  # бросит JobAlreadyRunning
        threading.Thread(target=self._execute, args=(job, cfg), daemon=True).start()
        return job

    def _prepare_config(self, cfg: InstallConfig) -> None:
        cfg.version = cfg.version.strip() or "latest"
        cfg.project_name = self._settings.default_project_name
        cfg.lib_dir_host = self._settings.lib_dir_host
        if not any(u.strip() for u in cfg.public_urls):
            cfg.public_urls = ["http://localhost"]

        # Переустановка: пустые секреты наследуются из существующего .env,
        # чтобы не сломать инициализированные Postgres/Fernet-данные
        existing = self._lib.read_env()
        cfg.postgres_password = (
            cfg.postgres_password
            or existing.get("DVT_POSTGRES_PASSWORD", "")
            or domain.generate_password()
        )
        cfg.valkey_password = (
            cfg.valkey_password
            or existing.get("DVT_VALKEY_PASSWORD", "")
            or domain.generate_password()
        )
        cfg.grpc_token = (
            cfg.grpc_token
            or existing.get("DVT_GRPC_FORWARD_SERVICE_TOKEN", "")
            or domain.generate_password()
        )
        cfg.fernet_key = (
            cfg.fernet_key.strip()
            or existing.get("DVT_FERNET_KEY", "")
            or domain.generate_fernet_key()
        )
        domain.populate_install_auth_secrets(cfg, existing)
        cfg.ai_mcp_internal_secret = (
            cfg.ai_mcp_internal_secret.strip()
            or existing.get("DVT_AI_MCP_INTERNAL_SECRET", "")
        )
        if cfg.ai_mcp_enabled and not cfg.ai_mcp_internal_secret:
            cfg.ai_mcp_internal_secret = domain.generate_password()
        if not domain.is_valid_fernet_key(cfg.fernet_key):
            raise ValueError(
                "Некорректный формат Fernet-ключа (ожидается 43 url-safe base64 символа и '=')"
            )
        domain.validate_ai_mcp_secret(
            cfg.ai_mcp_internal_secret,
            enabled=cfg.ai_mcp_enabled,
        )

    # ---------- Выполнение ----------

    def _execute(self, job: Job, cfg: InstallConfig) -> None:
        steps = dict(INSTALL_STEPS)
        try:
            run_step(job, "check_docker", steps["check_docker"], lambda: self._check_docker(job))
            run_step(job, "prepare_dirs", steps["prepare_dirs"], lambda: self._prepare_dirs(job))
            run_step(
                job,
                "initialize_identity",
                steps["initialize_identity"],
                lambda: self._initialize_identity(job),
            )
            run_step(job, "write_env", steps["write_env"], lambda: self._write_env(job, cfg))
            run_step(
                job,
                "download_compose",
                steps["download_compose"],
                lambda: self._download_compose(job, cfg),
            )
            run_step(
                job, "create_network", steps["create_network"], lambda: self._create_network(job)
            )
            run_step(job, "compose_up", steps["compose_up"], lambda: self._compose_up(job, cfg))
            job.log("")
            job.log(f"✅ DVT запущен (версия {cfg.version}).")
            job.log(f"URL: {cfg.public_url}")
            job.finish(JobState.SUCCEEDED)
        except StepError as exc:
            job.finish(JobState.FAILED, str(exc))
        except Exception as exc:
            job.log(f"❌ Непредвиденная ошибка: {exc}")
            job.finish(JobState.FAILED, f"Непредвиденная ошибка: {exc}")

    # ---------- Шаги ----------

    def _check_docker(self, job: Job) -> str:
        if not self._docker.docker_available():
            raise StepError("Docker недоступен: проверьте, что Docker запущен и socket проброшен")
        if not self._docker.compose_available():
            raise StepError("Docker Compose (plugin) недоступен")
        job.log("✅ Docker и Docker Compose доступны")
        return "docker + compose OK"

    def _prepare_dirs(self, job: Job) -> str:
        try:
            self._lib.ensure_data_dirs()
        except OSError as exc:
            raise StepError(
                f"Не удалось создать каталоги в {self._settings.lib_dir_host}: {exc}"
            ) from exc
        job.log(f"✅ Каталоги созданы в {self._settings.lib_dir_host}")
        return self._settings.lib_dir_host

    def _initialize_identity(self, job: Job) -> str:
        existing = self._lib.read_instance_id()
        if existing:
            job.log(f"✅ Existing installation instance_id: {existing}")
            return existing
        instance_id = str(uuid.uuid4())
        self._lib.write_instance_id(instance_id)
        job.log(f"✅ Installation instance_id initialized: {instance_id}")
        return instance_id

    def _write_env(self, job: Job, cfg: InstallConfig) -> str:
        self._lib.write_env_text(domain.render_env_file(cfg), backup=True)
        job.log(f"✅ Конфигурация записана в {self._settings.lib_dir_host}/.env")
        return f"{self._settings.lib_dir_host}/.env"

    def _download_compose(self, job: Job, cfg: InstallConfig) -> str:
        url = f"{self._settings.raw_storage_url}/dvt/docker-compose.yaml?version={cfg.version}"
        job.log(f"Скачивание {url}...")
        try:
            resp = httpx.get(url, timeout=60, follow_redirects=True)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise StepError(f"Не удалось скачать docker-compose.yaml: {exc}") from exc
        self._lib.write_compose(resp.text, backup=True)
        job.log("✅ docker-compose.yaml сохранён")
        return url

    def _create_network(self, job: Job) -> str:
        res = self._docker.ensure_network(self._settings.network_name)
        if not res.ok:
            raise StepError(f"Не удалось создать сеть {self._settings.network_name}:\n{res.output}")
        job.log(f"✅ Сеть {self._settings.network_name} готова")
        return self._settings.network_name

    def _compose_up(self, job: Job, cfg: InstallConfig) -> str:
        if not cfg.ai_mcp_enabled:
            job.log("⚙️ AI MCP выключен: удаление ранее запущенного контейнера, если он существует")
            for cleanup_command in (
                ["stop", "dvt-ai-mcp"],
                ["rm", "-f", "dvt-ai-mcp"],
            ):
                cleanup_result = self._docker.compose(
                    project_name=cfg.project_name,
                    compose_files=[self._lib.compose_path],
                    command=cleanup_command,
                    on_line=job.log,
                    env_file=self._lib.env_path,
                )
                if not cleanup_result.ok:
                    raise StepError(
                        "Не удалось остановить выключенный сервис dvt-ai-mcp. "
                        "Проверьте Docker и повторите установку."
                    )

        command = [
            "up",
            "-d",
            "--remove-orphans",
            "--pull",
            "always",
            "--scale",
            f"{self._settings.task_worker_service}={cfg.task_workers_count}",
        ]

        last_code = 1
        for attempt in range(1, MAX_COMPOSE_ATTEMPTS + 1):
            job.log("")
            job.log(f"⚙️ Попытка {attempt}/{MAX_COMPOSE_ATTEMPTS}: docker compose up ...")
            res = self._docker.compose(
                project_name=cfg.project_name,
                compose_files=[self._lib.compose_path],
                command=command,
                on_line=job.log,
                env_file=self._lib.env_path,
            )
            last_code = res.code
            if res.ok:
                job.log("✅ docker compose up успешно выполнен")
                return f"успешно с попытки {attempt}"

            job.log(f"⚠️ docker compose up завершился с ошибкой (код {res.code})")
            job.log("")
            job.log("⚙️ Диагностика (containers/health/logs):")
            job.log(self._docker.diagnostics())

            if attempt < MAX_COMPOSE_ATTEMPTS:
                sleep_sec = attempt * 10
                job.log(f"⚙️ Подождём {sleep_sec}s и попробуем ещё раз...")
                time.sleep(sleep_sec)

        raise StepError(
            f"Не удалось запустить DVT после {MAX_COMPOSE_ATTEMPTS} попыток "
            f"(последний код: {last_code}). См. логи выше."
        )
