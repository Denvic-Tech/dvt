from dataclasses import dataclass


@dataclass(frozen=True)
class ProjectID:
    value: str


@dataclass(frozen=True)
class UserID:
    value: str


@dataclass(frozen=True)
class OrganizationID:
    value: str
