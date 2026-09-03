from pathlib import Path
from uuid import UUID

from ..domain.repositories import InstallationIdentityRepository


class FileInstallationIdentityRepository(InstallationIdentityRepository):
    def __init__(self, path: Path) -> None:
        self._path = path

    def get_instance_id(self) -> UUID | None:
        try:
            raw = self._path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return None
        if not raw:
            return None
        return UUID(raw)

    def save_instance_id(self, instance_id: UUID) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(".tmp")
        temporary.write_text(f"{instance_id}\n", encoding="utf-8")
        temporary.replace(self._path)
