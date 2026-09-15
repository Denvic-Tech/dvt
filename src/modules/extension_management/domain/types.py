from enum import StrEnum


class ExtensionDependencyStatus(StrEnum):
    NOT_INSTALLED = "not_installed"
    INSTALLING = "installing"
    READY = "ready"
    ERROR = "error"


class ExtensionPackageOperation(StrEnum):
    INSTALL = "install"
    UPGRADE = "upgrade"
    DOWNGRADE = "downgrade"
    REINSTALL = "reinstall"


__all__ = ["ExtensionDependencyStatus", "ExtensionPackageOperation"]
