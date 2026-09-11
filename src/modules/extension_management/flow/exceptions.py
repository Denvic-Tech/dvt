from src.exception_registry import RegisteredException


class ExtensionManagementFlowError(RegisteredException):
    """Use named flow exceptions instead of raising RegisteredException directly."""

    category = "EXTENSION_MANAGEMENT_FLOW_ERROR"
