from __future__ import annotations

from src.modules.db_catalog.domain import CatalogActor
from src.modules.db_catalog.domain.exceptions import (
    CatalogTableNotFoundError,
    DbCatalogDomainError,
)
from src.modules.db_catalog.facade import CatalogUseCases

from ...domain import (
    DatasetSchemaSource,
    ObservedField,
    SchemaActor,
    SchemaSourceNotFoundError,
    SchemaSourceUnavailableError,
)


class DbCatalogDatasetSchemaSource(DatasetSchemaSource):
    """Схема таблицы через существующий ленивый db_catalog (кэш Valkey, политика доступа)."""

    def __init__(self, catalog_use_cases: CatalogUseCases) -> None:
        self._use_cases = catalog_use_cases

    async def fetch_fields(
        self,
        *,
        connection_id: str,
        actor: SchemaActor,
        database: str | None,
        schema: str | None,
        table: str,
        bypass_cache: bool = False,
    ) -> tuple[ObservedField, ...]:
        try:
            response = await self._use_cases.get_table.execute(
                connection_id=connection_id,
                actor=CatalogActor(id=actor.id, organization_id=actor.organization_id, role=actor.role),
                bypass_cache=bypass_cache,
                table_name=table,
                schema_name=schema,
                database_name=database,
            )
        except CatalogTableNotFoundError as exc:
            raise SchemaSourceNotFoundError(str(exc)) from exc
        except DbCatalogDomainError as exc:
            raise SchemaSourceUnavailableError(str(exc)) from exc

        details = response.result.table
        if details is None:
            raise SchemaSourceNotFoundError(f"table {table!r} is not available in catalog")

        return tuple(
            ObservedField(
                name=column.name,
                dtype=column.dtype,
                nullable=column.nullable,
                ordinal=column.ordinal,
                primary_key=bool(column.primary_key),
                comment=column.comment,
            )
            for column in details.columns
        )
