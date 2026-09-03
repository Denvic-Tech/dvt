import asyncio
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Optional

from celery import Celery
from sqlmodel import select

from src.db.session import AsyncSessionLocal
from src.enums import ExtensionDepsStatus
from src.infra.celery import create_celery_app
from src.logger import logger
from src.models.extension import ExtensionRecord

import config


@dataclass
class ExtensionDependencyResult:
    """Результат операции с зависимостями расширения."""
    success: bool
    extension_name: str
    status: ExtensionDepsStatus
    error_message: Optional[str] = None
    dependencies_count: int = 0


class ExtensionDependencyManager:
    """Управляет зависимостями расширений.
    
    Отвечает за:
    - Установку зависимостей через pip
    - Обновление статуса установки в БД
    - Проверку доступности расширений для выполнения задач
    - Координацию задач установки через Celery
    """

    def __init__(self, celery_client: Optional[Celery] = None) -> None:
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
        async with AsyncSessionLocal() as session:
            async with session.begin():
                result = await session.execute(
                    select(ExtensionRecord).where(ExtensionRecord.name == extension_name).with_for_update()
                )
                extension = result.scalars().first()
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

        log.info(
            f"Installing extension '{extension_name}' requirements count={len(requirements)}"
        )
        try:
            await self.update_deps_status(extension_name, ExtensionDepsStatus.INSTALLING)
            completed = await asyncio.to_thread(
                subprocess.run,
                [sys.executable, "-m", "pip", "install", *requirements],
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
            for worker_name in active_workers.keys():
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

            logger.info(f"Broadcasted extension deps install to {sent_count} workers")
            return sent_count

        except Exception:
            logger.exception(
                "Failed to broadcast extension deps install",
            )
            return 0

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
                select(ExtensionRecord).where(ExtensionRecord.name.in_(extension_names))
            )
            extensions = {item.name: item for item in result.scalars().all()}

        missing = sorted(extension_names - set(extensions.keys()))
        not_ready = []
        
        for extension in extensions.values():
            if (
                not extension.is_installed
                or not extension.is_enabled
                or extension.deps_status != ExtensionDepsStatus.READY
            ):
                reason = []
                if not extension.is_installed:
                    reason.append("not_installed")
                if not extension.is_enabled:
                    reason.append("disabled")
                if extension.deps_status != ExtensionDepsStatus.READY:
                    reason.append(f"deps_{extension.deps_status.value.lower()}")
                not_ready.append(f"{extension.name}: {', '.join(reason)}")

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
        parts = []
        if missing:
            parts.append(f"missing: {', '.join(missing)}")
        if not_ready:
            parts.append(f"not_ready: {', '.join(not_ready)}")
        return f"Extension is not available ({'; '.join(parts)})"

    async def _load_extension(self, extension_name: str) -> Optional[ExtensionRecord]:
        """Загружает расширение из БД."""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(ExtensionRecord).where(ExtensionRecord.name == extension_name)
            )
            return result.scalars().first()

    def _extract_requirements(self, extension: ExtensionRecord) -> list:
        """Извлекает требования из манифеста расширения."""
        manifest = extension.manifest_json or {}
        requirements = manifest.get("requirements") or []
        return requirements if isinstance(requirements, list) else []


# Глобальный экземпляр для использования в Gateway
_dependency_manager: Optional[ExtensionDependencyManager] = None


def get_dependency_manager() -> ExtensionDependencyManager:
    """Получает глобальный менеджер зависимостей.
    
    Создает новый экземпляр с Celery-клиентом, если он еще не создан.
    """
    global _dependency_manager
    if _dependency_manager is None:
        _dependency_manager = ExtensionDependencyManager.create_with_celery()
    return _dependency_manager


def reset_dependency_manager() -> None:
    """Сбрасывает глобальный менеджер зависимостей.
    
    Используется для тестирования или пересоздания клиента.
    """
    global _dependency_manager
    _dependency_manager = None
