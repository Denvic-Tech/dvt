from src.exception_registry import RegisteredException


class DataCatalogDomainError(RegisteredException):
    category = "DATA_CATALOG_DOMAIN_ERROR"


class InvalidColumnSchemaError(DataCatalogDomainError):
    name = "INVALID_COLUMN_SCHEMA"
    code = "DATA_CATALOG_001"
    description = "Column schema is invalid."


class InvalidTableSchemaError(DataCatalogDomainError):
    name = "INVALID_TABLE_SCHEMA"
    code = "DATA_CATALOG_002"
    description = "Table schema is invalid."
