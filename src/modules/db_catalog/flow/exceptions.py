from src.exception_registry import RegisteredException


class DbCatalogFlowError(RegisteredException):
    """Use named flow exceptions instead of raising RegisteredException directly."""

    category = "DB_CATALOG_FLOW_ERROR"
