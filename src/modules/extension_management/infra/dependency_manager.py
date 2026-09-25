import asyncio
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import cache
from pathlib import Path

from celery import Celery
from sqlmodel import select

from src.db.session import AsyncSessionLocal
from src.enums import ExtensionDepsStatus
from src.infra.celery import create_celery_app
from src.logger import logger
from src.modules.extension_management.domain.policies import (
    build_availability_error_message,
    extension_readiness_reasons,
)
from src.modules.extension_management.infra.db_models import ExtensionRecord
from src.modules.extension_management.infra.identity import resolve_record
from src.modules.extension_management.infra.packages.dependencies import (
    build_extension_pip_install_command,
)

import config


@dataclass
class ExtensionDependencyResult:
    """Результат операции с зависимостями расширения."""
    success: bool
    extension_name: str
    status: ExtensionDepsStatus
    error_message: str | None = None
    dependencies_count: int = 0


class ExtensionDependencyManager:
    """Управляет зависимостями расширений.
    
    Отвечает за:
    - Установку зависимостей через pip
    - Обновление статуса установки в БД
    - Проверку доступности расширений для выполнения задач
    - Координацию задач установки через Celery
    """

    def __init__(self, celery_client: Celery | None = None) -> None:
        """Инициализирует менеджер зависимостей.
        
        Args:
            celery_client: Опциональный Celery-клиент для отправки задач.
                          Если не предоставлен, задачи не могут быть отправлены асинхронно.
        """
        self._celery_client = celery_client

    @classmethod
    def create_with_celery(cls) -> "ExtensionDependencyManager":
        """Создает менеджер с Celery-клиентом для Gateway."""
        celery_client = create_celery_app("gateway_extensions")
        return cls(celery_client=celery_client)

    async def update_deps_status(
        self,
        extension_name: str,
        status: ExtensionDepsStatus,
    ) -> bool:
        """Обновляет статус установки зависимостей расширения в БД.
        
        Args:
            extension_name: Имя расширения.
            status: Новый статус установки.
            
        Returns:
            True если расширение найдено и статус обновлен, False иначе.
        """
        async with AsyncSessionLocal() as session, session.begin():
            result = await session.execute(
                select(ExtensionRecord).with_for_update()
            )
            extension = resolve_record(result.scalars().all(), extension_name)
            if extension is None:
                logger.warning(
                    "Extension not found for deps status update",
                    extension_name=extension_name,
                )
                return False

            extension.deps_status = status
            extension.updated_at = datetime.now(UTC)
            session.add(extension)
            logger.debug(
                "Extension deps status updated",
                extension_name=extension_name,
                status=status,
            )
            return True

    async def install_dependencies(self, extension_name: str) -> ExtensionDependencyResult:
        """Устанавливает зависимости расширения.
        
        Выполняет установку через pip install в окружение воркера.
        
        Args:
            extension_name: Имя расширения для установки.
            
        Returns:
            Результат операции установки.
        """
        log = logger.bind(extension_name=extension_name)

        extension = await self._load_extension(extension_name)
        if extension is None:
            log.error("Extension not found in DB")
            await self.update_deps_status(extension_name, ExtensionDepsStatus.ERROR)
            return ExtensionDependencyResult(
                success=False,
                extension_name=extension_name,
                status=ExtensionDepsStatus.ERROR,
                error_message="Extension not found",
            )

        requirements = self._extract_requirements(extension)
        if not isinstance(requirements, list):
            log.error("Invalid manifest requirements type")
            await self.update_deps_status(extension_name, ExtensionDepsStatus.ERROR)
            return ExtensionDependencyResult(
                success=False,
                extension_name=extension_name,
                status=ExtensionDepsStatus.ERROR,
                error_message="Invalid requirements format",
            )

        requirements = [
            item for item in requirements if isinstance(item, str) and item.strip()
        ]
        if not requirements:
            log.info("No dependencies to install")
            await self.update_deps_status(extension_name, ExtensionDepsStatus.READY)
            return ExtensionDependencyResult(
                success=True,
                extension_name=extension_name,
                status=ExtensionDepsStatus.READY,
                dependencies_count=0,
            )

        log.bind(requirements_count=len(requirements)).info(
            "Installing extension requirements"
        )
        try:
            await self.update_deps_status(extension_name, ExtensionDepsStatus.INSTALLING)
            install_root = Path(extension.install_path) if extension.install_path else None
            if install_root is None:
                raise RuntimeError("Extension install path is not configured")
            completed = await asyncio.to_thread(
                subprocess.run,
                build_extension_pip_install_command(
                    requirements,
                    install_root=install_root,
                ),
                check=False,
                capture_output=True,
                text=True,
            )
            if completed.returncode != 0:
                stderr = (completed.stderr or completed.stdout or "").strip()
                raise RuntimeError(stderr or "pip install failed")

            await self.update_deps_status(extension_name, ExtensionDepsStatus.READY)
            log.info("Extension dependencies installed")
            return ExtensionDependencyResult(
                success=True,
                extension_name=extension_name,
                status=ExtensionDepsStatus.READY,
                dependencies_count=len(requirements),
            )
        except Exception as exc:
            log.exception("Failed to install extension dependencies")
            await self.update_deps_status(extension_name, ExtensionDepsStatus.ERROR)
            return ExtensionDependencyResult(
                success=False,
                extension_name=extension_name,
                status=ExtensionDepsStatus.ERROR,
                error_message=str(exc),
            )

    def broadcast_install_task(self, extension_name: str) -> int:
        """Отправляет задачу на установку зависимостей каждому активному воркеру.

        Args:
            extension_name: Имя расширения для установки.

        Returns:
            Количество воркеров, которым отправлена задача.
        """
        if self._celery_client is None:
            logger.error(
                "Cannot broadcast install task: Celery client not initialized",
            )
            return 0

        try:
            # Получаем список активных воркеров
            i = self._celery_client.control.inspect()
            active_workers = i.active()

            if not active_workers:
                logger.warning("No active workers found to broadcast extension deps install")
                return 0

            sent_count = 0
            for worker_name in active_workers:
                try:
                    self._celery_client.send_task(
                        "task_worker.install_extension_deps",
                        args=[{"extension_name": extension_name}],
                        queue=config.CELERY.CELERY_DEPS_QUEUE,
                        exchange=config.CELERY.CELERY_DEPS_EXCHANGE,
                        routing_key=config.CELERY.CELERY_DEPS_QUEUE,
                        destination=[worker_name],  # Отправка конкретному воркеру
                    )
                    logger.debug(f"Sent extension deps install task to worker {worker_name}")
                    sent_count += 1
                except Exception as exc:
                    logger.warning(
                        f"Failed to send extension deps install task to worker {worker_name}: {exc}"
                    )

        except Exception:
            logger.exception(
                "Failed to broadcast extension deps install",
            )
            return 0
        else:
            logger.info(f"Broadcasted extension deps install to {sent_count} workers")
            return sent_count

    async def check_extensions_availability(
        self,
        extension_names: set[str],
    ) -> tuple[list[str], list[str]]:
        """Проверяет доступность расширений для выполнения задачи.
        
        Args:
            extension_names: Множество имен расширений, используемых в пайплайне.
            
        Returns:
            Кортеж (missing, not_ready):
            - missing: расширения, отсутствующие в БД
            - not_ready: расширения, которые не установлены, отключены или чьи зависимости не READY
        """
        if not extension_names:
            return [], []

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(ExtensionRecord)
            )
            records = result.scalars().all()
            extensions = {
                name: record for name in extension_names
                if (record := resolve_record(records, name)) is not None
            }

        missing = sorted(extension_names - set(extensions.keys()))
        not_ready = []

        for extension in extensions.values():
            reasons = extension_readiness_reasons(
                is_installed=extension.is_installed,
                is_enabled=extension.is_enabled,
                deps_status=extension.deps_status.value,
            )
            if reasons:
                not_ready.append(f"{extension.name}: {', '.join(reasons)}")

        return missing, not_ready

    def build_availability_error_message(
        self,
        missing: list[str],
        not_ready: list[str],
    ) -> str:
        """Формирует сообщение об ошибке недоступности расширений.
        
        Args:
            missing: Список отсутствующих расширений.
            not_ready: Список неготовых расширений.
            
        Returns:
            Форматированное сообщение об ошибке.
        """
        return build_availability_error_message(missing, not_ready)

    async def _load_extension(self, extension_name: str) -> ExtensionRecord | None:
        """Загружает расширение из БД."""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(ExtensionRecord)
            )
            return resolve_record(result.scalars().all(), extension_name)

    def _extract_requirements(self, extension: ExtensionRecord) -> list:
        """Извлекает требования из манифеста расширения."""
        manifest = extension.manifest_json or {}
        requirements = manifest.get("requirements") or []
        return requirements if isinstance(requirements, list) else []


@cache
def get_dependency_manager() -> ExtensionDependencyManager:
    """Получает process-local менеджер зависимостей с Celery-клиентом."""
    return ExtensionDependencyManager.create_with_celery()


def reset_dependency_manager() -> None:
    """Сбрасывает process-local менеджер зависимостей."""
    get_dependency_manager.cache_clear()
