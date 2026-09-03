from db_connection import AccessDeniedError, ConnectionNotFoundError

from core.db.connect.sqlalchemy_url import split_backend_and_driver

from src.modules.db_catalog.domain import (
    AuthorizedCatalogConnection,
    CatalogActor,
    CatalogConnectionUnavailableError,
    CatalogUnsupportedError,
)
from src.modules.db_catalog.domain.gateways import ConnectionAccessGateway
from src.node_dsl.connection_types import SqlConnectionRecord
from src.node_dsl.runtime.connections import resolve_sql_connection_url


class DVTConnectionAccessGateway(ConnectionAccessGateway):
    def __init__(self, connection_service) -> None:
        self._connection_service = connection_service

    async def get_authorized(
        self,
        connection_id: str,
        actor: CatalogActor,
    ) -> AuthorizedCatalogConnection:
        try:
            record = await self._connection_service.get(connection_id, actor=actor)
        except (AccessDeniedError, ConnectionNotFoundError) as exc:
            raise CatalogConnectionUnavailableError("DB connection is unavailable.") from exc

        if str(record.kind).lower() != "sql":
            raise CatalogUnsupportedError("Only SQL connections support the DB catalog fast path.")

        wrapped = SqlConnectionRecord(record)
        url = resolve_sql_connection_url(wrapped)
        backend, _driver = split_backend_and_driver(url)
        revision = getattr(record, "updated_at", None)
        revision_value = revision.isoformat() if revision is not None else "unversioned"
        return AuthorizedCatalogConnection(
            id=record.id,
            revision=revision_value,
            dialect=backend.lower(),
            configured_database=url.database,
            connection_url=url.render_as_string(hide_password=False),
        )
