from uuid import uuid4

from ..domain.entities import InstallationIdentity
from ..domain.repositories import InstallationIdentityRepository, MachineFingerprintProvider


class GetInstallationIdentity:
    def __init__(
        self,
        repository: InstallationIdentityRepository,
        fingerprint_provider: MachineFingerprintProvider | None = None,
    ) -> None:
        self._repository = repository
        self._fingerprint_provider = fingerprint_provider

    def execute(self) -> InstallationIdentity:
        instance_id = self._repository.get_instance_id()
        if instance_id is None:
            instance_id = uuid4()
            self._repository.save_instance_id(instance_id)
        fingerprint = (
            self._fingerprint_provider.get_machine_fingerprint()
            if self._fingerprint_provider is not None
            else None
        )
        return InstallationIdentity(
            instance_id=instance_id,
            machine_fingerprint=fingerprint,
        )
