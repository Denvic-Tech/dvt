"""Каталог данных DVT (DVT_LIB_DIR хоста), примонтированный в контейнер.

Installation identity хранится рядом с persistent state и не зависит от hardware/hostname.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from ..domain import services as domain
from ..domain.ports import DvtLibrary

DATA_SUBDIRS = ("data/pgdata", "data/valkeydata", "installation", "extensions")


class MountedDvtLibrary(DvtLibrary):
    def __init__(self, mount: Path):
        self._mount = mount

    @property
    def _env_file(self) -> Path:
        return self._mount / ".env"

    @property
    def _compose_file(self) -> Path:
        return self._mount / "docker-compose.yaml"

    @property
    def _instance_id_file(self) -> Path:
        return self._mount / "installation" / "instance_id"

    @property
    def env_path(self) -> str:
        return str(self._env_file)

    @property
    def compose_path(self) -> str:
        return str(self._compose_file)

    def installed(self) -> bool:
        try:
            return self._env_file.is_file() and bool(self._env_file.read_text(encoding="utf-8").strip())
        except OSError:
            return False

    def read_env_text(self) -> str:
        try:
            return self._env_file.read_text(encoding="utf-8")
        except OSError:
            return ""

    def read_env(self) -> dict[str, str]:
        return domain.parse_env_file(self.read_env_text())

    def write_env_text(self, content: str, backup: bool = True) -> None:
        if backup and self._env_file.is_file():
            self._backup(self._env_file)
        self._env_file.parent.mkdir(parents=True, exist_ok=True)
        self._env_file.write_text(content, encoding="utf-8")

    def write_compose(self, content: str, backup: bool = True) -> None:
        if backup and self._compose_file.is_file():
            self._backup(self._compose_file)
        self._compose_file.parent.mkdir(parents=True, exist_ok=True)
        self._compose_file.write_text(content, encoding="utf-8")

    def ensure_data_dirs(self) -> None:
        for sub in DATA_SUBDIRS:
            (self._mount / sub).mkdir(parents=True, exist_ok=True)

    def read_instance_id(self) -> str:
        try:
            return self._instance_id_file.read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def write_instance_id(self, instance_id: str) -> None:
        self._instance_id_file.parent.mkdir(parents=True, exist_ok=True)
        self._instance_id_file.write_text(instance_id + "\n", encoding="utf-8")

    @staticmethod
    def _backup(path: Path) -> None:
        stamp = datetime.now().strftime("%Y%m%d%H%M%S")
        path.replace(path.with_name(f"{path.name}.bak.{stamp}"))
