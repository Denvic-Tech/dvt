import platform
import sys
from typing import Annotated, Literal

from packaging.version import InvalidVersion, Version
from pydantic import BaseModel, Field, HttpUrl

import config

from src.modules.extension_management.domain.catalog import (
    CatalogRelease,
    CatalogVersion,
    RuntimeTarget,
    stable_upgrade,
)
from src.modules.extension_management.domain.policies import (
    release_incompatibility,
    resolve_package_operation,
)


class ReleasePayload(BaseModel):
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+(?:rc[0-9]+)?$")
    channel: Literal["stable", "rc"]
    dvt_version: str | None
    target: RuntimeTarget
    size_bytes: int = Field(strict=True, gt=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    download_url: HttpUrl

    def to_domain(self) -> CatalogRelease:
        return CatalogRelease(
            version=self.version,
            channel=self.channel,
            dvt_version=self.dvt_version,
            target=self.target,
            size_bytes=self.size_bytes,
            sha256=self.sha256,
            download_url=str(self.download_url),
        )


class ExtensionPayload(BaseModel):
    name: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    display_name: str
    description: str
    versions: Annotated[list[ReleasePayload], Field(min_length=1)]


class CatalogPayload(BaseModel):
    extensions: list[ExtensionPayload]


def runtime_target() -> RuntimeTarget:
    architecture = platform.machine().lower()
    if architecture == "amd64":
        architecture = "x86_64"
    return RuntimeTarget(
        os=platform.system().lower(),
        architecture=architecture,
        python=f"{sys.version_info.major}.{sys.version_info.minor}",
        implementation=platform.python_implementation(),
    )


def catalog_view(
    rows: list[dict], current_version: str | None
) -> tuple[list[CatalogVersion], str | None]:
    releases = sorted(
        (ReleasePayload.model_validate(row).to_domain() for row in rows),
        key=lambda release: Version(release.version),
        reverse=True,
    )
    versions = []
    stable = None
    target = runtime_target()
    for release in releases:
        reason = release_incompatibility(
            release, current_dvt_version=config.APP.VERSION or None, target=target
        )
        operation = None
        if reason is None:
            try:
                operation = resolve_package_operation(current_version, release.version).value
            except InvalidVersion:
                pass
            if stable is None and release.channel == "stable":
                stable = release.version
        versions.append(
            CatalogVersion(
                version=release.version,
                channel=release.channel,
                download_url=release.download_url,
                dvt_version=release.dvt_version,
                incompatibility=reason,
                operation=operation,
            )
        )
    return versions, stable_upgrade(stable, current_version)
