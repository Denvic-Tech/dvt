from pathlib import Path

import config

from .domain.entities import InstallationIdentity
from .flow.get_installation_identity import GetInstallationIdentity
from .infra.file_repository import FileInstallationIdentityRepository


class InstallationIdentityFacade:
    """Stable public capability facade for extensions and DVT host code."""

    API_VERSION = "1.0"

    def __init__(self, identity_file: Path | None = None) -> None:
        path = identity_file or config.PROJECT.INSTALLATION_IDENTITY_FILE
        self._use_case = GetInstallationIdentity(FileInstallationIdentityRepository(path))

    def get(self) -> InstallationIdentity:
        return self._use_case.execute()


def get_installation_identity() -> InstallationIdentity:
    return InstallationIdentityFacade().get()
