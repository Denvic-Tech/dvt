from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class InstallationIdentity:
    """Stable identity of one DVT installation.

    ``instance_id`` is random and persisted with DVT state. The optional machine
    fingerprint is advisory capability data and is never the source of identity.
    """

    instance_id: UUID
    machine_fingerprint: str | None = None
