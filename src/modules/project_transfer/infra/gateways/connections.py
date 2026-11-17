from __future__ import annotations

from typing import Any

from db_connection import AccessDeniedError, ConnectionDraft, ConnectionNotFoundError
from db_connection.application.service import ConnectionService
from db_connection.domain import ConnectionListQuery, ConnectionRecord
from db_connection.errors import SecretDecryptionError

from src.logger import logger
from src.modules.project_transfer.domain.entities import BundleConnection
from src.modules.project_transfer.domain.gateways import ConnectionCatalogGateway
from src.modules.project_transfer.domain.value_objects import ExistingConnection, TransferActor


def _plain(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", exclude_none=True)
    return dict(value) if isinstance(value, dict) else value


def _normalize_type(value: Any) -> str:
    return str(getattr(value, "value", value))


class ConnectionServiceGateway(ConnectionCatalogGateway):
    """Adapter over the shared ``db_connection`` service.

    ``service_actor`` is the authenticated user record the service's access policy
    understands; the domain ``TransferActor`` is only used for ownership of
    created connections.
    """

    def __init__(self, service: ConnectionService, *, service_actor: Any) -> None:
        self._service = service
        self._service_actor = service_actor

    async def _get(self, connection_id: str) -> ConnectionRecord | None:
        try:
            return await self._service.get(connection_id, actor=self._service_actor)
        except (ConnectionNotFoundError, AccessDeniedError):
            return None
        except SecretDecryptionError:
            logger.warning("Connection {} has unreadable secrets; exporting without them", connection_id)
            return None

    async def describe(
        self,
        connection_id: str,
        *,
        actor: TransferActor,  # noqa: ARG002 - access is enforced by the service actor
        ref: str,
    ) -> BundleConnection | None:
        record = await self._get(connection_id)
        if record is None:
            return None
        return BundleConnection(
            ref=ref,
            name=record.name,
            kind=_normalize_type(record.kind),
            type=_normalize_type(record.type),
            driver=record.driver,
            driver_options=_plain(record.driver_options),
            properties=dict(record.properties or {}),
            labels=dict(record.labels or {}),
        )

    async def read_secrets(
        self,
        connection_id: str,
        *,
        actor: TransferActor,  # noqa: ARG002
    ) -> dict[str, Any] | None:
        record = await self._get(connection_id)
        if record is None:
            return None
        return dict(record.secrets or {})

    async def exists(self, connection_id: str, *, actor: TransferActor) -> bool:  # noqa: ARG002
        return await self._get(connection_id) is not None

    async def find_candidates(
        self,
        connection: BundleConnection,
        *,
        actor: TransferActor,  # noqa: ARG002
    ) -> list[ExistingConnection]:
        try:
            records = await self._service.list(
                ConnectionListQuery(type=connection.type, name=connection.name),
                actor=self._service_actor,
            )
        except AccessDeniedError:
            return []
        return [
            ExistingConnection(
                id=record.id,
                name=record.name,
                kind=_normalize_type(record.kind),
                type=_normalize_type(record.type),
            )
            for record in records
            if record.deleted_at is None
        ]

    async def create(
        self,
        connection: BundleConnection,
        *,
        secrets: dict[str, Any],
        actor: TransferActor,
    ) -> str:
        draft = ConnectionDraft(
            name=connection.name,
            kind=connection.kind,
            type=connection.type,
            driver=connection.driver,
            driver_options=connection.driver_options,
            properties=dict(connection.properties),
            secrets=dict(secrets),
            labels=dict(connection.labels),
            metadata={"imported": True},
            extra={"user_id": actor.user_id, "organization_id": actor.organization_id},
        )
        record = await self._service.create(draft, actor=self._service_actor)
        return record.id
