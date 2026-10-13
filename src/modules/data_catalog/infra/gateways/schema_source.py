from __future__ import annotations

from typing import TYPE_CHECKING

from ...domain import (
    DatasetLocator,
    DatasetSchemaSource,
    DbTableLocator,
    ObservedField,
    SchemaActor,
    SchemaSourceNotFoundError,
    SchemaSourceUnavailableError,
)

if TYPE_CHECKING:
    from src.modules.db_catalog.facade import CatalogUseCases


class DbCatalogDatasetSchemaSource(DatasetSchemaSource):
    """Схема таблицы через существующий ленивый db_catalog (кэш Valkey, политика доступа).

    db_catalog импортируется лениво: его инфраструктура тянет core.metadata и botocore, а модели
    каталога импортируют сервисы (Project Scheduler), которым это недоступно и не нужно.
    """

    def __init__(self, catalog_use_cases: CatalogUseCases) -> None:
        self._use_cases = catalog_use_cases

    async def fetch_fields(
        self,
        *,
        connection_id: str,
        actor: SchemaActor,
        locator: DatasetLocator,
        bypass_cache: bool = False,
    ) -> tuple[ObservedField, ...]:
        from src.modules.db_catalog.domain import CatalogActor
        from src.modules.db_catalog.domain.exceptions import (
            CatalogTableNotFoundError,
            DbCatalogDomainError,
        )

        table_locator = DbTableLocator.from_locator(locator)
        table = table_locator.table
        try:
            response = await self._use_cases.get_table.execute(
                connection_id=connection_id,
                actor=CatalogActor(id=actor.id, organization_id=actor.organization_id, role=actor.role),
                bypass_cache=bypass_cache,
                table_name=table,
                schema_name=table_locator.schema,
                database_name=table_locator.database,
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
