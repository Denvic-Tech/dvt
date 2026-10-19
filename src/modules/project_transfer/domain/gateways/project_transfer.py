from __future__ import annotations

from typing import Any, Protocol

from ..entities import BundleConnection, ScheduleSnapshot
from ..value_objects import ExistingConnection, InstanceInfo, NodeTypeInfo, TransferActor


class ConnectionCatalogGateway(Protocol):
    async def describe(
        self,
        connection_id: str,
        *,
        actor: TransferActor,
        ref: str,
    ) -> BundleConnection | None:
        """Secret-free view of a connection; None when it does not exist or is inaccessible."""
        ...

    async def read_secrets(
        self,
        connection_id: str,
        *,
        actor: TransferActor,
    ) -> dict[str, Any] | None: ...

    async def exists(self, connection_id: str, *, actor: TransferActor) -> bool: ...

    async def find_candidates(
        self,
        connection: BundleConnection,
        *,
        actor: TransferActor,
    ) -> list[ExistingConnection]:
        """Accessible connections with the same type and name."""
        ...

    async def create(
        self,
        connection: BundleConnection,
        *,
        secrets: dict[str, Any],
        actor: TransferActor,
    ) -> str:
        """Create a connection owned by the actor; returns its id."""
        ...


class ScheduleGateway(Protocol):
    async def read(self, project_id: str) -> ScheduleSnapshot | None: ...

    async def disable(self, project_id: str) -> None: ...

    async def apply(
        self,
        project_id: str,
        schedule: ScheduleSnapshot,
        *,
        enabled: bool,
        actor: TransferActor,
        replace_existing: bool,
    ) -> None:
        """Create the schedule for a project, or overwrite the existing one when allowed."""
        ...


class NodeTypeCatalog(Protocol):
    async def describe(self, node_name: str) -> NodeTypeInfo: ...


class SecretsCipher(Protocol):
    def encrypt(self, payload: dict[str, Any], *, passphrase: str) -> bytes: ...

    def decrypt(self, blob: bytes, *, passphrase: str) -> dict[str, Any]:
        """Raises ``InvalidPassphraseError`` when the passphrase does not match."""
        ...


class InstanceInfoProvider(Protocol):
    def get(self) -> InstanceInfo: ...
