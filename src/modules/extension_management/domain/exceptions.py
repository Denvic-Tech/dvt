from src.exception_registry import RegisteredException


class ExtensionManagementDomainError(RegisteredException):
    """Use named domain exceptions instead of raising RegisteredException directly."""

    category = "EXTENSION_MANAGEMENT_DOMAIN_ERROR"
