from typing import Protocol

from ..entities import AuthorizedCatalogConnection, CatalogActor


class ConnectionAccessGateway(Protocol):
    async def get_authorized(
        self,
        connection_id: str,
        actor: CatalogActor,
    ) -> AuthorizedCatalogConnection: ...
