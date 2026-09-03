from dataclasses import dataclass

from .types import CatalogOperation, CatalogTableKind


@dataclass(frozen=True, slots=True)
class CatalogRequest:
    operation: CatalogOperation
    database_name: str | None = None
    schema_name: str | None = None
    table_name: str | None = None
    search: str | None = None
    cursor: str | None = None
    limit: int = 100
    kinds: tuple[CatalogTableKind, ...] = (
        CatalogTableKind.TABLE,
        CatalogTableKind.VIEW,
    )


@dataclass(frozen=True, slots=True)
class CatalogTablePreviewRequest:
    table_name: str
    database_name: str | None = None
    schema_name: str | None = None
