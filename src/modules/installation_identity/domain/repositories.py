from typing import Protocol
from uuid import UUID


class InstallationIdentityRepository(Protocol):
    def get_instance_id(self) -> UUID | None: ...

    def save_instance_id(self, instance_id: UUID) -> None: ...


class MachineFingerprintProvider(Protocol):
    def get_machine_fingerprint(self) -> str | None: ...
