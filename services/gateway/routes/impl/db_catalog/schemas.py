from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

CatalogPreviewValue = str | int | float | bool | None


class CatalogMetaSchema(BaseModel):
    catalog_version: str
    loaded_at: datetime
    expires_at: datetime
    cache_status: Literal["hit", "miss", "bypass"]


class CatalogDatabaseSummarySchema(BaseModel):
    name: str
    is_current: bool = False


class CatalogSchemaSummarySchema(BaseModel):
    name: str
    database_name: str | None = None


class CatalogTableSummarySchema(BaseModel):
    name: str
    kind: Literal["table", "view"]
    database_name: str | None = None
    schema_name: str | None = None


class CatalogColumnSchema(BaseModel):
    name: str
    ordinal: int = Field(ge=1)
    dtype: str
    nullable: bool | None = None
    indexed: bool = False
    primary_key: bool = False
    indexes: list[str] = Field(default_factory=list)


class CatalogTableDetailsSchema(CatalogTableSummarySchema):
    columns: list[CatalogColumnSchema]


class CatalogDatabasePageSchema(BaseModel):
    items: list[CatalogDatabaseSummarySchema]
    next_cursor: str | None = None
    meta: CatalogMetaSchema


class CatalogSchemaPageSchema(BaseModel):
    items: list[CatalogSchemaSummarySchema]
    next_cursor: str | None = None
    meta: CatalogMetaSchema


class CatalogTablePageSchema(BaseModel):
    items: list[CatalogTableSummarySchema]
    next_cursor: str | None = None
    meta: CatalogMetaSchema


class CatalogTableDetailsResponseSchema(BaseModel):
    item: CatalogTableDetailsSchema
    meta: CatalogMetaSchema


class CatalogTablePreviewColumnSchema(BaseModel):
    name: str
    dtype: str


class CatalogTablePreviewResponseSchema(BaseModel):
    columns: list[CatalogTablePreviewColumnSchema]
    rows: list[list[CatalogPreviewValue]]
    truncated: bool = False


class CatalogRefreshResponseSchema(BaseModel):
    catalog_version: str
