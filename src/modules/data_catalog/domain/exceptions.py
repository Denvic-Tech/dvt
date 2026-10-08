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


class DatasetNotFoundError(DataCatalogDomainError):
    name = "DATASET_NOT_FOUND"
    code = "DATA_CATALOG_004"
    description = "Dataset was not found or is not visible to the current user."


class DatasetAccessDeniedError(DataCatalogDomainError):
    name = "DATASET_ACCESS_DENIED"
    code = "DATA_CATALOG_005"
    description = "Dataset is not accessible to the current user."


class ExpressionUnresolvedError(DataCatalogDomainError):
    name = "DATA_CATALOG_EXPRESSION_UNRESOLVED"
    code = "DATA_CATALOG_006"
    description = "Locator expression cannot be resolved statically."


class SqlReferenceExtractionError(DataCatalogDomainError):
    name = "DATA_CATALOG_SQL_REFERENCE_EXTRACTION_FAILED"
    code = "DATA_CATALOG_007"
    description = "Table references cannot be extracted from SQL."


class SchemaSourceUnavailableError(DataCatalogDomainError):
    name = "DATASET_SCHEMA_SOURCE_UNAVAILABLE"
    code = "DATA_CATALOG_008"
    description = "Dataset schema source is unavailable."


class ProjectGraphNotFoundError(DataCatalogDomainError):
    name = "DATA_CATALOG_PROJECT_GRAPH_NOT_FOUND"
    code = "DATA_CATALOG_009"
    description = "Project graph for catalog projection was not found."


class DatasetFieldNotFoundError(DataCatalogDomainError):
    name = "DATASET_FIELD_NOT_FOUND"
    code = "DATA_CATALOG_012"
    description = "Dataset field was not found."


class FieldRenameNotApplicableError(DataCatalogDomainError):
    name = "DATASET_FIELD_RENAME_NOT_APPLICABLE"
    code = "DATA_CATALOG_013"
    description = "Dataset field rename cannot be confirmed for the given fields."


class InvalidFieldReferenceError(DataCatalogDomainError):
    name = "DATASET_FIELD_REFERENCE_INVALID"
    code = "DATA_CATALOG_014"
    description = "Dataset field reference is invalid."


class SchemaSourceNotFoundError(SchemaSourceUnavailableError):
    """Источник доступен, но объявленной базы или таблицы в нём нет: локатор ноды устарел."""

    name = "DATASET_SCHEMA_SOURCE_NOT_FOUND"
    code = "DATA_CATALOG_015"
    description = "Dataset table or database does not exist in the source."
