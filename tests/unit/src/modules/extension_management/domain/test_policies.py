import pytest

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


def test_filter_compatible_versions_respects_prod_channel() -> None:
    versions = [
        {"version": "2.0.0rc1", "dvt_version": ">=1.0.0"},
        {"version": "1.5.0", "dvt_version": ">=1.0.0,<2.0.0"},
        {"version": "1.4.0", "dvt_version": ">=2.0.0"},
    ]

    result = filter_compatible_versions(
        versions,
        current_dvt_version="1.22.0",
        channel="prod",
    )

    assert [item["version"] for item in result] == ["1.5.0"]


def test_readiness_reasons_are_composable() -> None:
    assert extension_readiness_reasons(
        is_installed=False,
        is_enabled=False,
        deps_status="installing",
    ) == ("not_installed", "disabled", "deps_installing")
