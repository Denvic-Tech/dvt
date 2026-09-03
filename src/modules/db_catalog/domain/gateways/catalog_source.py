from typing import Protocol

from ..entities import AuthorizedCatalogConnection, CatalogResult
from ..value_objects import CatalogRequest


class CatalogSourceGateway(Protocol):
    async def fetch(
        self,
        connection: AuthorizedCatalogConnection,
        request: CatalogRequest,
    ) -> CatalogResult: ...
