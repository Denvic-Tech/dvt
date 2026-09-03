from src.exception_registry import RegisteredException


class DbCatalogDomainError(RegisteredException):
    category = "DB_CATALOG_DOMAIN_ERROR"


class CatalogConnectionUnavailableError(DbCatalogDomainError):
    category = "DB_CATALOG_CONNECTION_UNAVAILABLE"


class CatalogUnsupportedError(DbCatalogDomainError):
    category = "DB_CATALOG_UNSUPPORTED"


class CatalogRequestValidationError(DbCatalogDomainError):
    category = "DB_CATALOG_REQUEST_INVALID"


class CatalogTableNotFoundError(DbCatalogDomainError):
    category = "DB_CATALOG_TABLE_NOT_FOUND"


class CatalogSourceUnavailableError(DbCatalogDomainError):
    category = "DB_CATALOG_SOURCE_UNAVAILABLE"


class CatalogSourceTimeoutError(DbCatalogDomainError):
    category = "DB_CATALOG_SOURCE_TIMEOUT"


class CatalogPreviewTooLargeError(DbCatalogDomainError):
    category = "DB_CATALOG_PREVIEW_TOO_LARGE"


class CatalogCacheUnavailableError(DbCatalogDomainError):
    category = "DB_CATALOG_CACHE_UNAVAILABLE"
