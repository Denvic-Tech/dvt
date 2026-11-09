from dataclasses import dataclass, field
from typing import Literal

from packaging.version import InvalidVersion, Version


@dataclass(frozen=True)
class RuntimeTarget:
    os: str
    architecture: str
    python: str
    implementation: str


@dataclass(frozen=True)
class CatalogRelease:
    version: str
    channel: Literal["stable", "rc"]
    dvt_version: str | None
    target: RuntimeTarget
    size_bytes: int
    sha256: str
    download_url: str


type CompatibilityField = Literal["os", "architecture", "python", "implementation", "dvt_version"]


@dataclass(frozen=True)
class CompatibilityDifference:
    field: CompatibilityField
    current: str | None
    required: str


@dataclass(frozen=True)
class CatalogVersion:
    version: str
    channel: Literal["stable", "rc"]
    download_url: str
    dvt_version: str | None
    incompatibility: Literal["target", "dvt_version"] | None
    operation: str | None
    incompatibility_details: list[CompatibilityDifference] = field(default_factory=list)


def stable_upgrade(stable_version: str | None, current_version: str | None) -> str | None:
    if stable_version is None or current_version is None:
        return stable_version
    try:
        return stable_version if Version(stable_version) > Version(current_version) else None
    except InvalidVersion:
        return None
