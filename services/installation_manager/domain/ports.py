"""Порты (интерфейсы) доменного слоя. Реализации — в infrastructure."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class CommandResult:
    code: int
    output: str

    @property
    def ok(self) -> bool:
        return self.code == 0


class DockerGateway(ABC):
    @abstractmethod
    def docker_available(self) -> bool: ...

    @abstractmethod
    def compose_available(self) -> bool: ...

    @abstractmethod
    def project_running(self, project_name: str, exclude_service: str = "") -> bool:
        """Есть ли запущенные контейнеры compose-проекта (кроме exclude_service)."""

    @abstractmethod
    def ensure_network(self, name: str) -> CommandResult: ...

    @abstractmethod
    def compose(
        self,
        project_name: str,
        compose_files: list[str],
        command: list[str],
        on_line: Callable[[str], None],
        env_file: str | None = None,
        project_dir: str | None = None,
    ) -> CommandResult:
        """Запуск docker compose <command> с потоковым выводом."""

    @abstractmethod
    def diagnostics(self) -> str:
        """Сводка контейнеров/health/логов для диагностики после ошибки."""


class DvtLibrary(ABC):
    """Каталог данных DVT (DVT_LIB_DIR), примонтированный в контейнер."""

    @abstractmethod
    def installed(self) -> bool: ...

    @abstractmethod
    def read_env(self) -> dict[str, str]: ...

    @abstractmethod
    def read_env_text(self) -> str: ...

    @abstractmethod
    def write_env_text(self, content: str, backup: bool = True) -> None: ...

    @abstractmethod
    def write_compose(self, content: str, backup: bool = True) -> None: ...

    @abstractmethod
    def ensure_data_dirs(self) -> None: ...

    @abstractmethod
    def read_instance_id(self) -> str: ...

    @abstractmethod
    def write_instance_id(self, instance_id: str) -> None: ...

    @property
    @abstractmethod
    def compose_path(self) -> str: ...

    @property
    @abstractmethod
    def env_path(self) -> str: ...
