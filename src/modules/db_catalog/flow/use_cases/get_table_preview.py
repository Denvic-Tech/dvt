from ...domain import (
    CatalogActor,
    CatalogTablePreviewRequest,
    CatalogTablePreviewResponse,
)
from ...domain.gateways import ConnectionAccessGateway, TablePreviewSourceGateway
from ...domain.policies import validate_table_preview_request


class GetTablePreviewUseCase:
    def __init__(
        self,
        *,
        connection_access: ConnectionAccessGateway,
        source: TablePreviewSourceGateway,
    ) -> None:
        self._connection_access = connection_access
        self._source = source

    async def execute(
        self,
        *,
        connection_id: str,
        actor: CatalogActor,
        table_name: str,
        database_name: str | None = None,
        schema_name: str | None = None,
    ) -> CatalogTablePreviewResponse:
        request = CatalogTablePreviewRequest(
            table_name=table_name,
            database_name=database_name,
            schema_name=schema_name,
        )
        connection = await self._connection_access.get_authorized(connection_id, actor)
        validate_table_preview_request(connection, request)
        preview = await self._source.fetch_preview(connection, request)
        return CatalogTablePreviewResponse(preview=preview, dialect=connection.dialect)
