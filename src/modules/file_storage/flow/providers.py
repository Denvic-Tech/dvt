from __future__ import annotations

from .connections import ResolvedStorageConnection
from .gateways import FileStorageGateway, StorageGatewayFactory


class FileStorageProvider:
    def __init__(
        self,
        *,
        connection: ResolvedStorageConnection,
        gateway_factory: StorageGatewayFactory,
    ) -> None:
        self._connection = connection
        self._gateway_factory = gateway_factory

    async def get_gateway(self) -> FileStorageGateway:
        return self._gateway_factory.build(self._connection)
