from enum import StrEnum


class CatalogOperation(StrEnum):
    DATABASES = "databases"
    SCHEMAS = "schemas"
    TABLES = "tables"
    TABLE = "table"


class CatalogTableKind(StrEnum):
    TABLE = "table"
    VIEW = "view"


class CatalogCacheStatus(StrEnum):
    HIT = "hit"
    MISS = "miss"
    BYPASS = "bypass"
