import re
from collections.abc import Iterable, Mapping
from typing import Any

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from src.modules.extension_management.domain.types import (
    ExtensionDependencyStatus,
    ExtensionPackageOperation,
)


def normalize_extension_identity(value: str | None) -> str:
    """Normalize human/catalog and package extension names to a comparable identity."""
    if not value:
        return ""
    return re.sub(r"[\W_]+", "-", value.strip().casefold(), flags=re.UNICODE).strip("-")


def resolve_package_operation(
    current_version: str | None,
    package_version: str,
) -> ExtensionPackageOperation:
    if current_version is None:
        return ExtensionPackageOperation.INSTALL
    current = Version(current_version)
    package = Version(package_version)
    if package > current:
        return ExtensionPackageOperation.UPGRADE
    if package < current:
        return ExtensionPackageOperation.DOWNGRADE
    return ExtensionPackageOperation.REINSTALL


def is_dvt_version_compatible(
    *,
    current_dvt_version: str | None,
    required_dvt_version: str | None,
) -> bool:
    if not current_dvt_version or required_dvt_version in {None, "*"}:
        return True
    try:
        return Version(current_dvt_version) in SpecifierSet(
            required_dvt_version,
            prereleases=True,
        )
    except (InvalidVersion, InvalidSpecifier):
        return False


def filter_compatible_versions(
    versions: Iterable[Mapping[str, Any]],
    *,
    current_dvt_version: str | None,
    channel: str,
) -> list[dict[str, Any]]:
    normalized = [dict(item) for item in versions]
    if not current_dvt_version:
        return normalized

    compatible: list[dict[str, Any]] = []
    for item in normalized:
        version_str = item.get("version")
        if channel.lower() == "prod" and isinstance(version_str, str):
            try:
                if Version(version_str).is_prerelease:
                    continue
            except InvalidVersion:
                pass

        required_dvt_version = item.get("dvt_version")
        if required_dvt_version in {None, "*"}:
            compatible.append(item)
            continue
        try:
            if Version(current_dvt_version) in SpecifierSet(
                str(required_dvt_version), prereleases=True
            ):
                compatible.append(item)
        except (InvalidVersion, InvalidSpecifier):
            # Keep distributor entries with malformed compatibility metadata for
            # backwards compatibility; package validation will still run before activation.
            compatible.append(item)
    return compatible


def extension_readiness_reasons(
    *,
    is_installed: bool,
    is_enabled: bool,
    deps_status: ExtensionDependencyStatus | str,
) -> tuple[str, ...]:
    value = (
        deps_status.value
        if isinstance(deps_status, ExtensionDependencyStatus)
        else str(deps_status)
    )
    reasons: list[str] = []
    if not is_installed:
        reasons.append("not_installed")
    if not is_enabled:
        reasons.append("disabled")
    if value != ExtensionDependencyStatus.READY.value:
        reasons.append(f"deps_{value.lower()}")
    return tuple(reasons)


def build_availability_error_message(
    missing: list[str],
    not_ready: list[str],
) -> str:
    parts: list[str] = []
    if missing:
        parts.append(f"missing: {', '.join(missing)}")
    if not_ready:
        parts.append(f"not_ready: {', '.join(not_ready)}")
    return f"Extension is not available ({'; '.join(parts)})"


__all__ = [
    "build_availability_error_message",
    "extension_readiness_reasons",
    "filter_compatible_versions",
    "is_dvt_version_compatible",
    "normalize_extension_identity",
    "resolve_package_operation",
]
