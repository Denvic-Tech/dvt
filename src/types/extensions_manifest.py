"""Compatibility exports for the extension-management domain manifest types."""

from src.modules.extension_management.domain.value_objects import (
    ExtensionBackendManifest,
    ExtensionFrontendManifest,
    ExtensionManifest,
    ExtensionNodeManifest,
)

__all__ = [
    "ExtensionBackendManifest",
    "ExtensionFrontendManifest",
    "ExtensionManifest",
    "ExtensionNodeManifest",
]
