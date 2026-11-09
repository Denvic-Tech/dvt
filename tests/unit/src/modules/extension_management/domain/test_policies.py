from dataclasses import replace

import pytest

from src.modules.extension_management.domain.catalog import CatalogRelease, RuntimeTarget

from src.modules.extension_management.domain.policies import (
    extension_readiness_reasons,
    filter_compatible_versions,
    is_dvt_version_compatible,
    resolve_package_operation,
)
from src.modules.extension_management.domain.types import ExtensionPackageOperation


@pytest.mark.parametrize(
    ("current", "package", "expected"),
    [
        (None, "1.0.0", ExtensionPackageOperation.INSTALL),
        ("1.0.0", "1.1.0", ExtensionPackageOperation.UPGRADE),
        ("1.1.0", "1.0.0", ExtensionPackageOperation.DOWNGRADE),
        ("1.0.0", "1.0.0", ExtensionPackageOperation.REINSTALL),
    ],
)
def test_resolve_package_operation(current, package, expected) -> None:
    assert resolve_package_operation(current, package) == expected


def test_is_dvt_version_compatible_supports_prerelease_runtime() -> None:
    assert is_dvt_version_compatible(
        current_dvt_version="1.22.0rc1",
        required_dvt_version=">=1.22.0-rc1",
    )


def test_filter_compatible_versions_checks_runtime_and_keeps_rc() -> None:
    target = RuntimeTarget("linux", "x86_64", "3.13", "CPython")
    stable = CatalogRelease("1.5.0", "stable", ">=1.0.0", target, 1, "a" * 64, "https://example")
    rc = replace(stable, version="2.0.0rc1", channel="rc")
    versions = [
        stable,
        replace(stable, version="3.0.0", dvt_version=">=2.0.0"),
        replace(stable, version="4.0.0", target=replace(target, os="windows")),
        replace(stable, version="5.0.0", dvt_version="not-a-specifier"),
        rc,
    ]

    result = filter_compatible_versions(versions, current_dvt_version="1.22.0", target=target)

    assert result == [rc, stable]


def test_readiness_reasons_are_composable() -> None:
    assert extension_readiness_reasons(
        is_installed=False,
        is_enabled=False,
        deps_status="installing",
    ) == ("not_installed", "disabled", "deps_installing")
