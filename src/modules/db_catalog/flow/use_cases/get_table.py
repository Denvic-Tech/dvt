from ...domain import CatalogActor, CatalogOperation, CatalogRequest
from ..providers import CatalogProvider


class GetTableUseCase:
    def __init__(self, provider: CatalogProvider) -> None:
        self._provider = provider

    async def execute(
        self,
        *,
        connection_id: str,
        actor: CatalogActor,
        bypass_cache: bool = False,
        **query,
    ):
        return await self._provider.execute(
            connection_id=connection_id,
            actor=actor,
            request=CatalogRequest(operation=CatalogOperation.TABLE, **query),
            bypass_cache=bypass_cache,
        )
