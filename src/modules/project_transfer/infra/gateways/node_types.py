from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src.enums import ExtensionDepsStatus
from src.modules.extension_management.infra.db_models import ExtensionRecord
from src.modules.project_transfer.domain.gateways import NodeTypeCatalog
from src.modules.project_transfer.domain.value_objects import NodeTypeInfo
from src.node_dsl import registry
from src.node_dsl.node_typing import IO, contains_exact_io

CONNECTION_ID_TYPES = (
    IO.DB_CONNECTION_ID,
    IO.S3_CONNECTION_ID,
    IO.FTP_CONNECTION_ID,
    IO.SMB_CONNECTION_ID,
    IO.KAFKA_CONNECTION_ID,
)


def _connection_input_names(node_name: str) -> tuple[str, ...]:
    try:
        definition = registry.get_definition(node_name)
    except KeyError:
        return ()
    names = []
    for attr_name, input_def in definition.input_definitions.items():
        if any(contains_exact_io(input_def.type, io_type) for io_type in CONNECTION_ID_TYPES):
            names.append(str(attr_name))
    return tuple(names)


class RegistryNodeTypeCatalog(NodeTypeCatalog):
    """Resolves node class names through the node registry and the extensions table."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._cache: dict[str, NodeTypeInfo] = {}
        self._extensions: dict[str, ExtensionRecord | None] = {}

    async def _extension(self, name: str) -> ExtensionRecord | None:
        if name not in self._extensions:
            self._extensions[name] = (
                await self._session.execute(sa.select(ExtensionRecord).where(ExtensionRecord.name == name))
            ).scalars().first()
        return self._extensions[name]

    async def describe(self, node_name: str) -> NodeTypeInfo:
        if node_name in self._cache:
            return self._cache[node_name]

        node_classes = registry.get_all_nodes()
        node_cls = node_classes.get(node_name)
        if node_cls is None:
            info = NodeTypeInfo(name=node_name, known=False)
        else:
            extension_name = getattr(node_cls, "EXTENSION_NAME", None)
            extension_version = None
            extension_available = True
            if extension_name:
                extension = await self._extension(extension_name)
                extension_available = bool(
                    extension is not None
                    and extension.is_installed
                    and extension.is_enabled
                    and extension.deps_status == ExtensionDepsStatus.READY
                )
                extension_version = extension.current_version if extension is not None else None
            info = NodeTypeInfo(
                name=node_name,
                known=True,
                extension_name=extension_name,
                extension_version=extension_version,
                extension_available=extension_available,
                connection_input_names=_connection_input_names(node_name),
            )
        self._cache[node_name] = info
        return info
