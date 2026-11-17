from src.exception_registry import RegisteredException


class DataCatalogInfraError(RegisteredException):
    category = "DATA_CATALOG_INFRA_ERROR"


class DataFrameSchemaMappingError(DataCatalogInfraError):
    name = "DATAFRAME_SCHEMA_MAPPING_ERROR"
    code = "DATA_CATALOG_003"
    description = "DataFrame cannot be converted to a table schema."


class DataCatalogPersistenceError(DataCatalogInfraError):
    name = "DATA_CATALOG_PERSISTENCE_ERROR"
    code = "DATA_CATALOG_010"
    description = "Data catalog persistence operation failed."
