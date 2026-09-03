from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any

from db_connection.registry import ConnectionRegistry
from db_connection.errors import ValidationFailedError
from db_connection.application.service import ConnectionService
from db_connection.application.validation import ValidationService
from db_connection.domain import ConnectionRecord

from ..actor import DVTActor
from ...validation_compat import normalize_connection_record_for_validation


@dataclass(slots=True)
class ResolvedConnectionClient:
    client: Any
    connection: ConnectionRecord
    type: str
    kind: str
    driver: str | None

    async def aclose(self) -> None:
        for method_name in ("aclose", "close", "dispose"):
            method = getattr(self.client, method_name, None)
            if not callable(method):
                continue

            result = method()
            if inspect.isawaitable(result):
                await result
            return


class ResolveConnectionClientUseCase:
    def __init__(
        self,
        *,
        service: ConnectionService,
        registry: ConnectionRegistry,
    ) -> None:
        self._service = service
        self._registry = registry
        self._validation = ValidationService(registry)

    async def execute(
        self,
        *,
        connection_id: str,
        actor: DVTActor | None = None,
    ) -> ResolvedConnectionClient:
        connection = await self._service.get(connection_id, actor=actor)
        spec = self._registry.get_type(connection.type)
        if "client" not in spec.capabilities or spec.connector_factory is None:
            raise ValidationFailedError(
                f"Connection type '{connection.type}' does not support runtime client resolution."
            )

        validated = self._validation.validate(normalize_connection_record_for_validation(connection))
        client = await spec.connector_factory().get_client(validated)
        return ResolvedConnectionClient(
            client=client,
            connection=connection,
            type=connection.type,
            kind=connection.kind,
            driver=validated.driver,
        )
