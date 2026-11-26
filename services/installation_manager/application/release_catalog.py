"""Read the Distribution catalog and verify the chosen transition before saving its pin."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

from packaging.version import Version
from pydantic import Field, StringConstraints

from ..domain.operation_state import FailureReason, ReleasePin
from ..domain.release_manifest import (
    Digest,
    Platform,
    ReleaseId,
    ReleaseManifest,
    Revision,
    StagingError,
    UtcDate,
    VersionText,
    WireModel,
    canonical_json,
    strict_json,
)
from ..infrastructure.catalog_files import (
    read_catalog,
    read_selected_manifest,
    write_catalog,
    write_selected_manifest,
)
from ..infrastructure.release_verification import MAX_MANIFEST_BYTES, invalid_package
from ..infrastructure.staging_downloads import https_origin
from ..infrastructure.staging_host import incompatible

CATALOG_PATH = "/api/v1/dvt/releases"
MAX_CATALOG_BYTES = 2 * 1024 * 1024
MAX_CACHE_BYTES = MAX_CATALOG_BYTES + 4096


def version_tag(value: str) -> str:
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:-?rc[1-9][0-9]*)?", value):
        raise ValueError("Unsupported DVT version")
    parsed = Version(value)
    if parsed.pre:
        return f"{parsed.base_version}-rc{parsed.pre[1]}"
    return parsed.base_version


class CatalogSourceRelease(WireModel):
    version: VersionText
    revision: Revision


class CatalogRelease(WireModel):
    format_version: Literal[1]
    version: VersionText
    channel: Literal["stable", "rc"]
    release_id: ReleaseId
    published_at: UtcDate
    platforms: Annotated[list[Platform], Field(min_length=1, max_length=2)]
    distributions: dict[str, list[str]]
    initial_install: bool
    target_revision: Revision
    from_releases: list[CatalogSourceRelease]
    manifest_digest: Digest
    manifest_url: Annotated[str, StringConstraints(min_length=1, max_length=2048)]

    @property
    def pin(self) -> ReleasePin:
        return ReleasePin(self.release_id, self.manifest_digest)


class CatalogDocument(WireModel):
    format_version: Literal[1]
    releases: Annotated[list[CatalogRelease], Field(max_length=1024)]


@dataclass(frozen=True)
class CatalogHost:
    platform: str
    distribution: str
    distribution_version: str


@dataclass(frozen=True)
class SourceFacts:
    version: str
    revision: str


@dataclass(frozen=True)
class CatalogSnapshot:
    releases: tuple[CatalogRelease, ...] = ()
    fetched_at: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class SelectedRelease:
    pin: ReleasePin
    manifest_url: str
    following: tuple[ReleasePin, ...] = ()


class ReleaseCatalog:
    def __init__(
        self,
        *,
        data: Path,
        origin: str,
        host: CatalogHost,
        download: Callable[[str, int], bytes],
        verify: Callable[[bytes, ReleasePin], ReleaseManifest] | None,
    ) -> None:
        if urlsplit(origin).path not in ("", "/"):
            raise ValueError("Configure the HTTPS origin of the Distributor")
        self.data = data
        self.origin = https_origin(origin)
        self.host = host
        self.download = download
        self.verify = verify

    def _manifest_url(self, version: str, digest: str) -> str:
        return f"{self.origin}{CATALOG_PATH}/{version}/manifest/{digest}"

    def _parse(self, value: object) -> tuple[CatalogRelease, ...]:
        releases = CatalogDocument.model_validate(value).releases
        versions = set()
        for row in releases:
            version = Version(row.version)
            if (
                row.version != version_tag(row.version)
                or version in versions
                or version.is_prerelease != (row.channel == "rc")
                or row.manifest_url != self._manifest_url(row.version, row.manifest_digest)
                or any(Version(route.version) >= version for route in row.from_releases)
            ):
                raise ValueError("Invalid DVT catalog entry or immutable URL")
            versions.add(version)
        return tuple(sorted(releases, key=lambda row: Version(row.version)))

    def refresh(self) -> CatalogSnapshot:
        try:
            raw = self.download(self.origin + CATALOG_PATH, MAX_CATALOG_BYTES)
            if len(raw) > MAX_CATALOG_BYTES:
                raise ValueError
            value = strict_json(raw)
            releases = self._parse(value)
        except StagingError as error:
            reason = error.reason.value
        except OSError:
            reason = FailureReason.DISTRIBUTOR_UNAVAILABLE.value
        except (ValueError, RecursionError):
            reason = FailureReason.INVALID_PACKAGE.value
        else:
            fetched_at = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
            cache = canonical_json({"origin": self.origin, "fetched_at": fetched_at, "catalog": value})
            try:
                if len(cache) > MAX_CACHE_BYTES:
                    raise ValueError("The encoded catalog exceeds the cache limit")
                write_catalog(self.data, cache)
            except (OSError, StagingError, ValueError):
                # A read-only/full disk is observable without breaking the running application.
                return CatalogSnapshot(releases, fetched_at, "catalog_cache_write_failed")
            return CatalogSnapshot(releases, fetched_at)

        try:
            raw = read_catalog(self.data, MAX_CACHE_BYTES)
            if raw is not None:
                cache = strict_json(raw)
                if cache["origin"] == self.origin:
                    fetched_at = cache["fetched_at"]
                    if not fetched_at.endswith("Z"):
                        raise ValueError
                    datetime.fromisoformat(fetched_at)
                    return CatalogSnapshot(self._parse(cache["catalog"]), fetched_at, reason)
        except (AttributeError, KeyError, OSError, StagingError, TypeError, ValueError, RecursionError):
            pass
        return CatalogSnapshot(error=reason)

    def supports_host(self, release: CatalogRelease) -> bool:
        return release.platforms.count(self.host.platform) == 1

    def paths(
        self, snapshot: CatalogSnapshot, observed: SourceFacts | None, *, allow_rc: bool = False
    ) -> dict[str, tuple[CatalogRelease, ...]]:
        """Compute shortest allowed routes in increasing version order; stable is the default."""
        start = (Version(observed.version), observed.revision) if observed else None
        states = {start: ()} if start is not None else {}
        paths = {}
        for row in snapshot.releases:
            if not self.supports_host(row) or (row.channel == "rc" and not allow_rc):
                continue
            if start is None:
                if row.initial_install:
                    paths[row.version] = (row,)
                continue
            candidates = [
                states[key]
                for route in row.from_releases
                if (key := (Version(route.version), route.revision)) in states
            ]
            if candidates:
                # Ties prefer the newer supported intermediate path deterministically.
                prefix = min(
                    sorted(candidates, key=lambda path: tuple(Version(r.version) for r in path),
                           reverse=True),
                    key=len,
                )
                paths[row.version] = states[(Version(row.version), row.target_revision)] = (
                    *prefix, row,
                )
        return paths

    def select_route(
        self, snapshot: CatalogSnapshot, target: CatalogRelease, observed: SourceFacts, *,
        allow_rc: bool = False,
    ) -> SelectedRelease:
        route = self.paths(snapshot, observed, allow_rc=allow_rc).get(target.version)
        if not route or route[-1].pin != target.pin:
            raise incompatible("No supported upgrade route to the selected release")
        selected = []
        for step in route:
            # Verify every incoming edge and cache every immutable manifest before admission.
            selected.append(self.select(step, observed, allow_rc=allow_rc))
            observed = SourceFacts(step.version, step.target_revision)
        first, *following = selected
        return SelectedRelease(first.pin, first.manifest_url, tuple(step.pin for step in following))

    def select(
        self,
        row: CatalogRelease,
        observed: SourceFacts | None,
        *,
        allow_rc: bool = False,
    ) -> SelectedRelease:
        if self.verify is None:
            raise invalid_package("No DVT release trust verifier is configured")
        url = self._manifest_url(row.version, row.manifest_digest)
        if row.version != version_tag(row.version) or row.manifest_url != url:
            raise invalid_package("The catalog does not provide the selected immutable manifest URL")
        if row.channel == "rc" and not allow_rc:
            raise incompatible("A release candidate requires explicit consent")
        content = read_selected_manifest(self.data, row.pin)
        if content is None:
            content = self.download(url, MAX_MANIFEST_BYTES)
        manifest = self.verify(content, row.pin)
        schema = manifest.database_schema
        host = self.host
        if (
            Version(manifest.version) != Version(row.version)
            or manifest.channel != row.channel
            or schema.target_revision != row.target_revision
        ):
            raise invalid_package("The selected catalog entry differs from the signed manifest")
        if host.platform not in manifest.platforms:
            raise incompatible("The selected release does not provide images for the observed platform")
        if observed is None:
            compatible = schema.initial_install
        else:
            compatible = any(
                Version(route.version) == Version(observed.version)
                and route.revision == observed.revision
                for route in schema.from_releases
            )
        if not compatible:
            raise incompatible("The observed source requires a different compatible release first")
        write_selected_manifest(self.data, row.pin, content)
        return SelectedRelease(row.pin, url)
