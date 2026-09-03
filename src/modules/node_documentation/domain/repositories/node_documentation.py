from typing import Protocol

from ..entities import PublishedNodeDocumentation


class NodeDocumentationRepository(Protocol):
    async def get(
        self,
        *,
        node_name: str,
        locale: str,
    ) -> PublishedNodeDocumentation | None: ...
