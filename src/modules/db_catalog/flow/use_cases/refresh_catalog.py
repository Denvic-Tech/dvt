from ...domain import CatalogActor
from ..providers import CatalogProvider


class RefreshCatalogUseCase:
    def __init__(self, provider: CatalogProvider) -> None:
        self._provider = provider

    async def execute(self, *, connection_id: str, actor: CatalogActor):
        return await self._provider.refresh(connection_id=connection_id, actor=actor)
