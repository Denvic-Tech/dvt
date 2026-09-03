from __future__ import annotations

from db_connection import ConnectionCheckResult, Connector, InfrastructureError, ValidatedConnection

from src.db import engine

from .client import DVTServiceFilesClient
from .schemas import DVTServiceFilesProperties


class DVTServiceFilesConnector(Connector):
    async def check(self, connection: ValidatedConnection) -> ConnectionCheckResult:
        try:
            client = await self.get_client(connection)
            entries = client.listdir()
            return ConnectionCheckResult(
                name=connection.name,
                connected=True,
                message=f"Connected to DVT service files. Entries: {len(entries)}.",
            )
        except Exception as exc:  # noqa: BLE001
            return ConnectionCheckResult(
                name=connection.name,
                connected=False,
                message=f"DVT service files check failed: {exc!s}",
                exception=str(exc),
            )

    async def get_client(self, connection: ValidatedConnection) -> DVTServiceFilesClient:
        properties = connection.properties
        if not isinstance(properties, DVTServiceFilesProperties):
            raise InfrastructureError(
                "DVT service files connection properties payload is invalid.",
                details={"received_type": type(properties).__name__},
            )

        return DVTServiceFilesClient(
            engine=engine,
            organization_id=properties.organization_id,
            project_id=properties.project_id,
            root_prefix=properties.root_prefix,
        )
