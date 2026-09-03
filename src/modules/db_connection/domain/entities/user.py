from dataclasses import dataclass


@dataclass(frozen=True)
class ExistingUser:
    id: str
    organization_id: str


@dataclass(frozen=True)
class DraftOrPatchUser:
    id: str | None
    organization_id: str | None
