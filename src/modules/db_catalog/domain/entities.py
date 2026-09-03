from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .types import CatalogCacheStatus, CatalogTableKind

CatalogPreviewValue = str | int | float | bool | None


@dataclass(frozen=True, slots=True)
class CatalogActor:
    id: str
    organization_id: str
    role: str


@dataclass(frozen=True, slots=True)
class CatalogCapabilities:
    supports_databases: bool
    supports_schemas: bool
    supports_tables: bool = True
    supports_views: bool = True
    supports_search: bool = True
    max_page_size: int = 200


@dataclass(frozen=True, slots=True)
class AuthorizedCatalogConnection:
    id: str
    revision: str
    dialect: str
    configured_database: str | None
    connection_url: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class CatalogDatabase:
    name: str
    is_current: bool = False


@dataclass(frozen=True, slots=True)
class CatalogSchema:
    name: str
    database_name: str | None = None


@dataclass(frozen=True, slots=True)
class CatalogTableSummary:
    name: str
    kind: CatalogTableKind
    database_name: str | None = None
    schema_name: str | None = None


@dataclass(frozen=True, slots=True)
class CatalogColumn:
    name: str
    ordinal: int
    dtype: str
    nullable: bool | None = None
    indexed: bool = False
    primary_key: bool = False
    indexes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CatalogTableDetails:
    name: str
    kind: CatalogTableKind
    columns: tuple[CatalogColumn, ...]
    database_name: str | None = None
    schema_name: str | None = None


@dataclass(frozen=True, slots=True)
class CatalogTablePreviewColumn:
    name: str
    dtype: str


@dataclass(frozen=True, slots=True)
class CatalogTablePreview:
    columns: tuple[CatalogTablePreviewColumn, ...]
    rows: tuple[tuple[CatalogPreviewValue, ...], ...]
    truncated: bool = False


@dataclass(frozen=True, slots=True)
class CatalogTablePreviewResponse:
    preview: CatalogTablePreview
    dialect: str


CatalogItem = CatalogDatabase | CatalogSchema | CatalogTableSummary


@dataclass(frozen=True, slots=True)
class CatalogResult:
    items: tuple[CatalogItem, ...] = ()
    next_cursor: str | None = None
    table: CatalogTableDetails | None = None


@dataclass(frozen=True, slots=True)
class CatalogCacheEntry:
    result: CatalogResult
    catalog_version: str
    loaded_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class CatalogResponse:
    result: CatalogResult
    dialect: str
    catalog_version: str
    loaded_at: datetime
    expires_at: datetime
    cache_status: CatalogCacheStatus


@dataclass(frozen=True, slots=True)
class CatalogRefreshResult:
    catalog_version: str
