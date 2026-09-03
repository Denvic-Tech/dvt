from typing import Protocol

from ..entities import AuthorizedCatalogConnection, CatalogTablePreview
from ..value_objects import CatalogTablePreviewRequest


class TablePreviewSourceGateway(Protocol):
    async def fetch_preview(
        self,
        connection: AuthorizedCatalogConnection,
        request: CatalogTablePreviewRequest,
    ) -> CatalogTablePreview: ...
