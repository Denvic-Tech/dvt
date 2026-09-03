"""Use case обновления DVT до заданной версии.

Прод-режим (по умолчанию): compose и .env берутся из каталога данных DVT
(DVT_LIB_DIR): версия обновляется в .env, скачивается compose нужной версии,
затем pull + up целевых сервисов.

Dev-режим (UPDATE_SERVICE_COMPOSE_FILES задан): работа с compose-файлами
репозитория, поддерживается UPDATE_SERVICE_MODE=build — поведение прежнего
update-service.
"""

from __future__ import annotations

import os
import threading

import httpx

from ..config import Settings
from ..domain import services as domain
from ..domain.models import Job, JobKind, JobState, UpdateConfig
from ..domain.ports import DockerGateway, DvtLibrary
from ..infrastructure.job_store import InMemoryJobStore
from .base import StepError, run_step

AI_MCP_SERVICE = "dvt-ai-mcp"

UPDATE_STEPS_PROD = [
    ("check_docker", "Проверка Docker"),
    ("update_env", "Обновление конфигурации (.env)"),
    ("download_compose", "Загрузка docker-compose.yaml"),
    ("pull", "Загрузка образов"),
    ("up", "Перезапуск сервисов"),
]

UPDATE_STEPS_DEV = [
    ("check_docker", "Проверка Docker"),
    ("pull", "Сборка/загрузка образов"),
    ("up", "Перезапуск сервисов"),
]


class UpdateUseCase:
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

    def start(self, cfg: UpdateConfig) -> Job:
        cfg.version = cfg.version.strip()
        if not cfg.version:
            raise ValueError("Не указана версия")
        if not self._settings.dev_mode and not self._lib.installed():
            raise ValueError(
                "Продукт не установлен: .env не найден в каталоге данных. Выполните установку."
            )

        current_env = dict(os.environ) if self._settings.dev_mode else self._lib.read_env()
        if cfg.ai_mcp_enabled is None:
            cfg.ai_mcp_enabled = domain.parse_bool_value(
                current_env.get("DVT_AI_MCP_ENABLED"),
                default=False,
            )
        cfg.ai_mcp_internal_secret = (
            cfg.ai_mcp_internal_secret.strip()
            or current_env.get("DVT_AI_MCP_INTERNAL_SECRET", "")
        )
        if cfg.ai_mcp_enabled and not cfg.ai_mcp_internal_secret:
            cfg.ai_mcp_internal_secret = domain.generate_password()
        domain.validate_ai_mcp_secret(
            cfg.ai_mcp_internal_secret,
            enabled=cfg.ai_mcp_enabled,
        )

        steps = UPDATE_STEPS_DEV if self._settings.dev_mode else UPDATE_STEPS_PROD
        job = Job(JobKind.UPDATE, steps)
        job.version = cfg.version
        self._jobs.start(job)  # бросит JobAlreadyRunning
        threading.Thread(target=self._execute, args=(job, cfg), daemon=True).start()
        return job

    # ---------- Выполнение ----------

    def _execute(self, job: Job, cfg: UpdateConfig) -> None:
        try:
            if self._settings.dev_mode:
                self._execute_dev(job, cfg)
            else:
                self._execute_prod(job, cfg)
            job.log("")
            job.log(f"✅ Обновление до версии {cfg.version} завершено.")
            job.finish(JobState.SUCCEEDED)
        except StepError as exc:
            job.finish(JobState.FAILED, str(exc))
        except Exception as exc:
            job.log(f"❌ Непредвиденная ошибка: {exc}")
            job.finish(JobState.FAILED, f"Непредвиденная ошибка: {exc}")

    def _execute_prod(self, job: Job, cfg: UpdateConfig) -> None:
        steps = dict(UPDATE_STEPS_PROD)
        run_step(job, "check_docker", steps["check_docker"], lambda: self._check_docker(job))
        run_step(job, "update_env", steps["update_env"], lambda: self._update_env(job, cfg))
        run_step(
            job,
            "download_compose",
            steps["download_compose"],
            lambda: self._download_compose(job, cfg),
        )
        env = self._lib.read_env()
        project = env.get("COMPOSE_PROJECT_NAME") or self._settings.default_project_name
        ai_mcp_enabled = cfg.ai_mcp_enabled is True
        targets = self._effective_targets(ai_mcp_enabled)
        compose_files = [self._lib.compose_path]
        env_file = self._lib.env_path

        if not ai_mcp_enabled:
            self._stop_ai_mcp(job, project, compose_files, env_file)

        run_step(
            job,
            "pull",
            steps["pull"],
            lambda: self._compose_stream(job, project, compose_files, ["pull", *targets], env_file),
        )

        up_command = ["up", "-d", "--no-deps"]
        if self._settings.task_worker_service in targets:
            workers = env.get("DVT_TASK_WORKERS_COUNT", "1")
            up_command += ["--scale", f"{self._settings.task_worker_service}={workers}"]
        up_command += targets
        run_step(
            job,
            "up",
            steps["up"],
            lambda: self._compose_stream(job, project, compose_files, up_command, env_file),
        )

    def _execute_dev(self, job: Job, cfg: UpdateConfig) -> None:
        steps = dict(UPDATE_STEPS_DEV)
        run_step(job, "check_docker", steps["check_docker"], lambda: self._check_docker(job))
        project = self._settings.default_project_name
        compose_files = [str(f) for f in self._settings.compose_files]
        project_dir = str(self._settings.project_dir) if self._settings.project_dir else None
        ai_mcp_enabled = cfg.ai_mcp_enabled is True
        targets = self._effective_targets(ai_mcp_enabled)
        env = {
            "DVT_VERSION": cfg.version,
            "DVT_AI_MCP_ENABLED": domain.render_bool(ai_mcp_enabled),
            "DVT_AI_MCP_INTERNAL_SECRET": cfg.ai_mcp_internal_secret,
            "COMPOSE_PROFILES": domain.update_ai_mcp_profile(
                os.environ.get("COMPOSE_PROFILES"),
                enabled=ai_mcp_enabled,
            ),
        }

        if not ai_mcp_enabled:
            self._stop_ai_mcp(
                job,
                project,
                compose_files,
                env_file=None,
                project_dir=project_dir,
                extra_env=env,
            )

        build_or_pull = "build" if self._settings.update_mode == "build" else "pull"
        run_step(
            job,
            "pull",
            steps["pull"],
            lambda: self._compose_stream(
                job,
                project,
                compose_files,
                [build_or_pull, *targets],
                env_file=None,
                project_dir=project_dir,
                extra_env=env,
            ),
        )
        run_step(
            job,
            "up",
            steps["up"],
            lambda: self._compose_stream(
                job,
                project,
                compose_files,
                ["up", "-d", "--no-deps", *targets],
                env_file=None,
                project_dir=project_dir,
                extra_env=env,
            ),
        )

    # ---------- Шаги ----------

    def _check_docker(self, job: Job) -> str:
        if not self._docker.docker_available():
            raise StepError("Docker недоступен")
        if not self._docker.compose_available():
            raise StepError("Docker Compose (plugin) недоступен")
        job.log("✅ Docker и Docker Compose доступны")
        return "docker + compose OK"

    def _update_env(self, job: Job, cfg: UpdateConfig) -> str:
        content = self._lib.read_env_text()
        existing = domain.parse_env_file(content)
        auth_secrets = domain.resolve_auth_secrets(existing)
        ai_mcp_enabled = cfg.ai_mcp_enabled is True
        updated = domain.update_env_values(
            content,
            {
                "DVT_VERSION": cfg.version,
                "DVT_AI_MCP_ENABLED": domain.render_bool(ai_mcp_enabled),
                "DVT_AI_MCP_INTERNAL_SECRET": cfg.ai_mcp_internal_secret,
                "COMPOSE_PROFILES": domain.update_ai_mcp_profile(
                    existing.get("COMPOSE_PROFILES"),
                    enabled=ai_mcp_enabled,
                ),
                **auth_secrets,
            },
        )
        self._lib.write_env_text(updated, backup=True)
        job.log(
            f"✅ DVT_VERSION={cfg.version}, DVT_AI_MCP_ENABLED="
            f"{domain.render_bool(ai_mcp_enabled)} записаны в .env (бэкап создан)"
        )
        return (
            f"DVT_VERSION={cfg.version}, "
            f"DVT_AI_MCP_ENABLED={domain.render_bool(ai_mcp_enabled)}"
        )

    def _effective_targets(self, ai_mcp_enabled: bool) -> list[str]:
        return [
            service
            for service in self._settings.target_services
            if ai_mcp_enabled or service != AI_MCP_SERVICE
        ]

    def _stop_ai_mcp(
        self,
        job: Job,
        project: str,
        compose_files: list[str],
        env_file: str | None,
        project_dir: str | None = None,
        extra_env: dict[str, str] | None = None,
    ) -> None:
        job.log("⚙️ AI MCP выключен: остановка и удаление контейнера, если он существует")
        for command in (["stop", AI_MCP_SERVICE], ["rm", "-f", AI_MCP_SERVICE]):
            self._compose_stream(
                job,
                project,
                compose_files,
                command,
                env_file,
                project_dir=project_dir,
                extra_env=extra_env,
            )

    def _download_compose(self, job: Job, cfg: UpdateConfig) -> str:
        url = f"{self._settings.raw_storage_url}/dvt/docker-compose.yaml?version={cfg.version}"
        job.log(f"Скачивание {url}...")
        try:
            resp = httpx.get(url, timeout=60, follow_redirects=True)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise StepError(f"Не удалось скачать docker-compose.yaml: {exc}") from exc
        self._lib.write_compose(resp.text, backup=True)
        job.log("✅ docker-compose.yaml обновлён (бэкап создан)")
        return url

    def _compose_stream(
        self,
        job: Job,
        project: str,
        compose_files: list[str],
        command: list[str],
        env_file: str | None,
        project_dir: str | None = None,
        extra_env: dict[str, str] | None = None,
    ) -> str:
        if extra_env:
            # DVT_VERSION для интерполяции compose в dev-режиме;
            # одновременно выполняется только один job
            os.environ.update(extra_env)
        res = self._docker.compose(
            project_name=project,
            compose_files=compose_files,
            command=command,
            on_line=job.log,
            env_file=env_file,
            project_dir=project_dir,
        )
        if not res.ok:
            job.log("")
            job.log("⚙️ Диагностика:")
            job.log(self._docker.diagnostics())
            raise StepError(f"docker compose {command[0]} завершился с кодом {res.code}")
        return f"docker compose {command[0]} OK"
